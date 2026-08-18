# The Algorithm — How Documents Become Answerable Facts

How a PDF becomes a set of independently retrievable, exactly-citable chunks,
and **why** each decision was made. Design rationale lives here; operational
detail lives in [DEPLOYMENT.md](../DEPLOYMENT.md).

The goal in one sentence: **every chunk is independently answerable and carries
an exact citation — document → page → table → row → bounding polygon.**

Known gaps are collected in [Phase 2](#phase-2--known-gaps) at the end. They are
stated plainly rather than hidden, because knowing what a system *doesn't* do is
what makes the rest trustworthy.

---

## Table of contents

- [Data sources](#data-sources)
- [Pipeline stages](#pipeline-stages)
- [Confidence-based routing](#confidence-based-routing-step-3)
- [Chunking strategy](#chunking-strategy-step-5)
- [Figure understanding](#figure-understanding-steps-4a4c)
- [Citation authority](#citation-authority)
- [Phase 2 — known gaps](#phase-2--known-gaps)

---

## Data sources

### 1. ADI JSON — structure and location

`prebuilt-layout` returns:

| Field | What it gives us |
|---|---|
| `pages[].words[]` | every word with a confidence score and span offsets |
| `tables[].cells[]` | cell content, row/column index, spans, bounding polygon |
| `figures[]` | figure bounding polygon + caption (**no image pixels**) |
| `paragraphs[]` | text blocks with a role (`title`, `sectionHeading`, `pageFooter`, …) |
| `content` | full document text in reading order |

**Key insight:** ADI gives us *structure and location*. Every cell and figure
carries `boundingRegions[].polygon` — 8 numbers locating it on the page. That is
what makes a citation verifiable rather than a claim.

> **Normalization is mandatory.** The SDK's `as_dict()` returns **camelCase**
> (`pageNumber`, `boundingRegions`, `rowIndex`) while the pipeline reads
> snake_case. Every artifact passes through `shared/adi_normalize.py` on write
> *and* defensively on read. This is not cosmetic — see
> [the page-1 bug](#why-normalization-is-not-optional).

### 2. ADI Markdown — readable structure

The same call with `outputContentFormat: "markdown"` adds `<!-- PageNumber -->`
markers, `<figure>`/`<figcaption>` blocks, and `<table>` markup. Saved as
`adi-content.md` for human review. It adds no pixels, no confidence scores, and
no polygons — those stay in the JSON.

### 3. OCR Markdown — the second reader *(currently disabled)*

Pages routed to OCR are re-read by a vision model, one page per request. Adds
clean pipe tables, LaTeX math, extracted images, and better reads of
low-confidence cells. Adds **no polygons and no confidence scores**, which is
precisely why it never becomes the citation authority.

`OCR_ENABLED=false` today — ADI handles all pages. See
[Phase 2](#phase-2--known-gaps).

---

## Pipeline stages

Blob upload → Event Grid → Durable orchestrator. Each step writes its artifact
to `processing/{doc_id}/{run_id}/`, so any stage is independently inspectable.

| Step | Does | Artifact |
|---|---|---|
| 1 | pre-analysis — page count, text presence | `step1-result.json` |
| 2 | ADI `prebuilt-layout` + **normalization** | `adi-raw.json`, `adi-content.md` |
| 3 | confidence routing — which pages need a second read | `routing.json` |
| 4 | OCR enrichment *(disabled)* | `mistral-page-N.md` |
| 4A/4B | figure crop + qualification | `figures.json` |
| 4C | vision understanding of qualified figures | `figure-understanding.json` |
| 5 | chunk composition | `chunks.json` |
| 6 | embedding | `chunks-embedded.json` |
| 7 | index upsert | `step7-result.json` |

`doc_id = sha256(content)[:16]` — **content only, not filename**. Re-uploading
identical bytes under a new name resolves to the same document rather than
duplicating it. (Caveat in [Phase 2](#phase-2--known-gaps).)

---

## Confidence-based routing (Step 3)

Deterministic. **No LLM involved** — the same page always routes the same way,
which is what makes the cost model predictable and the behaviour auditable.

| Signal | Action | Why |
|---|---|---|
| min cell confidence < 0.75 | → OCR | ADI itself reports it struggled |
| body cell with `rowSpan > 1` | → OCR | merged cells break row extraction |
| mixed orientation on the page | → OCR | rotated text degrades layout reads |
| figure overlaps a table (`OCR_FIGURE_ROUTING`) | → OCR | table likely rendered as an image |
| otherwise | accept ADI | the common case |

**Why not always use the vision model?** Cost and latency scale per page, and
ADI already wins on the majority of pages while being the only source of
polygons. The router exists so the expensive reader is spent only where the
cheap reader admitted weakness.

---

## Chunking strategy (Step 5)

Three chunk types, each answering a different *shape* of question.

<details>
<summary>Diagram — a 3-page PDF decomposed into chunks (click to expand)</summary>

<img src="diagrams/pdf-chunking-strategy.drawio.svg" width="900"
     alt="PDF chunking strategy — a 3-page PDF decomposed into paragraph, table-row and figure chunks"/>

</details>

### Table row chunks — one row per chunk

```json
{
  "chunk_id": "5746428c_p7_t0_r3",
  "type": "table_row",
  "text_for_embedding": "Table: Potentiodynamic polarization data | Inhibitor concentration (g): 6 | bc (V/dec): 0.3233 | Ecorr (V): -0.8027",
  "citation": { "page": 7, "table_index": 0, "row_index": 3, "bounding_polygon": [...] }
}
```

Headers are **fused into every row** so the chunk is self-contained: the bare
number `0.3233` is meaningless to a retriever, `bc (V/dec): 0.3233` is not.

**Why not embed the table inside the paragraph chunk?** Three problems: the
vector covers 500 tokens of mixed prose and numbers and drifts toward the page
topic, so a numeric query competes against noise; without headers the values are
unretrievable; and citation granularity collapses to page level, losing the
row polygon needed to highlight the exact cell.

**Why not one chunk per table?** Same problems at larger scale. A 50-row table
averages its vector across unrelated categories, forces the LLM to scan
everything to read one fact, and overflows `CHUNK_TOKENS` — requiring either
truncation (silent data loss) or a bigger window (further dilution). Row-level
chunking scales uniformly: a 5-row and a 500-row table produce chunks of
identical size and identical retrieval precision.

Two details that matter for ranking:

- **Table label prefix** — every row is prefixed `Table: <label>`, where label is
  the caption or, failing that, the normalized column headers. Computed once and
  reused verbatim in the paragraph pointer so the two always match.
- **Lead-in context** — the last 1–2 sentences of the nearest preceding prose
  paragraph are prepended as `Context: …`, anchoring rows to topical wording that
  never appears in the cells. Must exceed `CHUNK_LEAD_IN_MIN_CHARS` (default 30)
  to exclude UI labels and lone numbers.

### Paragraph chunks

Split at ~500 tokens with ~100 overlap (`CHUNK_TOKENS` / `CHUNK_OVERLAP_TOKENS`).
Three pre-processing passes run first:

1. **Role filtering** — `pageHeader`, `pageNumber`, `pageFooter` are dropped.
   Running titles repeat on every page and pull embeddings toward the document
   topic instead of the paragraph's content.
2. **Table cell exclusion** — ADI duplicates every cell into `paragraphs[]`.
   Unfiltered, they appear as context-free noise (`"0 0.0335 -0.939"`) while the
   same data already exists, correctly structured, as `table_row` chunks. Each
   run is replaced by one `[Table: <label>]` pointer, so the LLM knows structured
   data is available and what its columns are.
3. **Checkbox normalization** — `:selected:` / `:unselected:` become
   `[checked]` / `[unchecked]` so sentences stay readable.

Kept roles: `body`, `sectionHeading`, `title`.

The two types are designed to be **retrieved together**: `table_row` answers
*"what is X at Y?"*, `paragraph` answers *"why does X happen?"*.

### Figure chunks

One chunk per qualified figure, where `text_for_embedding` is the **vision
model's description**, not the caption. That is what makes
*"balance graph showing knee alignment gaps"* retrieve a chart whose caption
never uses those words.

---

## Figure understanding (Steps 4A–4C)

Full design: [figure-understanding-extension.md](figure-understanding-extension.md).

Three stages, deliberately ordered cheapest-first:

**4A — crop.** Convert the ADI polygon (inches) to points, pad slightly, render
at `CROP_DPI`.

**4B — qualify.** Geometric heuristics reject page furniture *before* any model
call: tiny area, extreme aspect ratio, header/footer overlap, repeated position
across pages (logos). On a 19-page catalog this rejected **21 of 57 figures —
37% of vision cost removed by arithmetic.**

**4C — understand.** One schema-enforced `gpt-4o-mini` call per survivor,
returning category, description, visible labels, and search keywords. Only
high-confidence negatives are rejected; uncertain figures are retained and
flagged `retain_low_confidence`, because a wrong reject is invisible while a
wrong retain is merely noisy.

`FIGURE_MAX_PER_DOC` (default 60) caps spend per document. **Figures beyond the
cap are never described** — a real constraint on large documents, visible in
`demo.py annotate` output.

---

## Citation authority

**ADI is always the citation authority, even when OCR provides better text.**

OCR output has no polygons and no confidence scores. If a citation pointed at
OCR text, it could not be located in the source PDF. So enrichment merges into
the ADI structure — text may improve, but `page`, `table_index`, `row_index`,
and `bounding_polygon` always come from ADI.

This is what lets every answer be checked against the original document rather
than trusted.

### Why normalization is not optional

Step 2 stored `result.as_dict()` — **camelCase**. Every downstream reader used
snake_case. Each lookup returned `None`, masked by an `or 1` default. The result:
**every citation in the system reported page 1**, silently, from day one.

The failure mode is the point. Nothing crashed; answers looked correct; only the
provenance was wrong — the one thing the system exists to guarantee. Fixed by
normalizing at write *and* on read (so existing artifacts self-repair), pinned by
13 regression tests in `tests/unit/test_adi_normalize.py`.

---

## Phase 2 — known gaps

Deliberate limitations, not oversights. Each is a real lever with a real cost.

### 1. Figures are described without page context ← highest impact

Today the vision model receives the cropped image, page number, ADI caption,
routing signals, and geometry — but **no surrounding page text and no
document-level context.**

The caption is usually absent: **only 8 of 57 figures** in the Surface catalog
had one, so 28 of 36 descriptions were generated with effectively no text
signal. The model describes a crop in isolation, unaware it is reading a
Surface education catalog or an orthopedic surgical technique guide.

Measured effect (cosine similarity, same corpus):

| Figure | Context available | Best query score |
|---|---|---|
| `Figure 3. Implant planning and balance graph…` | ADI caption present | **0.893** |
| `A group of students sitting on the floor…` | no caption | 0.780–0.83 vs. domain queries |

Captioned figures inherit domain vocabulary and rank strongly. Uncaptioned ones
get generic lifestyle prose that competes poorly against clinical queries.

**Fix:** pass (a) document-level context — filename plus a page-1 summary — and
(b) the paragraphs nearest the figure's bounding box. The proximity math already
exists in `step4a_figures.py` for reference detection, and the text is already in
`adi.json` with coordinates. No extra API calls.

**Cost:** redeploy + re-ingest. Changes existing descriptions.

### 2. No server-side vectorizer on the index

`vectorizers: []`, so the index cannot embed a query itself. Clients must supply
the vector — which `demo.py` does.

Consequence: **Azure AI Foundry's "add your data" cannot run vector search
against this index.** It fails outright, or worse, silently degrades to
keyword-only and quietly loses the semantic matching that makes figure retrieval
work. Full explanation in [DEMO.md](DEMO.md#why-the-demo-doesnt-use-foundrys-chat-ui).

**Fix:** attach an `azureOpenAI` vectorizer to the profile. ~20 minutes. Deferred
only because it touches a working index.

### 3. OCR path disabled

`OCR_ENABLED=false`. The router, merge logic, and normalization are implemented
and tested, but no Mistral OCR deployment is attached. Merged-cell tables and
low-confidence pages therefore keep ADI's best-effort output.

### 4. No relevance floor in retrieval

Search returns nearest neighbours regardless of quality, so a query nothing
depicts still yields results. `demo.py figures` now reports cosine similarity and
warns below threshold (measured: unrelated ≈0.78, genuine ≥0.87), but **the
pipeline itself applies no floor.**

### 5. `doc_id` ignores filename

`sha256(content)[:16]`. Two filenames with identical bytes collapse to one
document, and deleting either removes both. Correct for dedup, surprising for
versioned files.

### 6. Deferred test coverage

81 unit tests pass. OpenSpec tasks 3.6, 4.7 and 6.6 — figure qualification edge
cases — remain unwritten. Qualification was instead validated empirically across
330 real figures.

### 7. App Insights telemetry not flowing

Steps emit `step_start` / `step_end` / `step_error`, but traces are not reaching
App Insights. Diagnose via Durable storage tables meanwhile
(`DEPLOYMENT.md`). Cause is likely MCAPS policy-managed diagnostic settings.

---

## See also

- [README.md](../README.md) — capabilities, architecture, quick start
- [DEPLOYMENT.md](../DEPLOYMENT.md) — infrastructure, settings, operations
- [DEMO.md](DEMO.md) — presenting the pipeline
- [figure-understanding-extension.md](figure-understanding-extension.md) — full figure design
