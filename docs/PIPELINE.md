# Pipeline — How a PDF Becomes an Answerable Index

The ingestion spine: what happens between "PDF uploaded" and "chunk searchable
with an exact citation", and why each stage exists.

This is the **overview**. Two things are deliberately *not* repeated here, only
linked, because each is its own large concern:

- **How chunks are built** (table rows vs. paragraphs vs. figures, and why) →
  [CHUNKING.md](CHUNKING.md)
- **How figures are read and described** — the vision model call — →
  [figure-understanding-extension.md](figure-understanding-extension.md)

The goal in one sentence: **every chunk is independently answerable and carries
an exact citation — document → page → table → row → bounding polygon.**

---

## Table of contents

- [Data sources](#data-sources)
- [Pipeline stages](#pipeline-stages)
- [Confidence-based routing](#confidence-based-routing-step-3)
- [Citation authority](#citation-authority)
- [Phase 2 — known gaps](#phase-2-known-gaps)

---

## Data sources

Three sources feed the pipeline. Each gives you something the others don't.

### 1. ADI JSON — structure and location

Azure Document Intelligence `prebuilt-layout` returns:

| Field | What it gives us |
|---|---|
| `pages[].words[]` | every word with a confidence score and span offsets |
| `tables[].cells[]` | cell content, row/column index, spans, bounding polygon |
| `figures[]` | figure bounding polygon + caption (**no image pixels**) |
| `paragraphs[]` | text blocks with a role (`title`, `sectionHeading`, `pageFooter`, …) |
| `content` | full document text in reading order |

**Key insight:** ADI gives us *structure and location*. Every cell and figure
carries `boundingRegions[].polygon` — 8 numbers locating it on the page. That is
what makes a citation verifiable rather than a claim, and it is why ADI is
[always the citation authority](#citation-authority), even on pages that get a
second read.

> **Normalization is mandatory.** The SDK's `as_dict()` returns **camelCase**
> (`pageNumber`, `boundingRegions`, `rowIndex`) while the pipeline reads
> snake_case. Every artifact passes through `shared/adi_normalize.py` on write
> *and* defensively on read. Not cosmetic — see
> [why normalization is not optional](#why-normalization-is-not-optional).

### 2. ADI Markdown — readable structure

The same call with `outputContentFormat: "markdown"` adds `<!-- PageNumber -->`
markers, `<figure>`/`<figcaption>` blocks, and `<table>` markup. Saved as
`adi-content.md` for human review. It adds no pixels, no confidence scores, and
no polygons — those stay in the JSON.

### 3. OCR Markdown — the second reader *(currently disabled)*

Pages routed to OCR (see [confidence routing](#confidence-based-routing-step-3))
are re-read by a vision model, one page per request. Adds clean pipe tables,
LaTeX math, extracted images, and better reads of low-confidence cells. Adds
**no polygons and no confidence scores**, which is precisely why it never
becomes the citation authority.

`OCR_ENABLED=false` today — ADI handles all pages. See
[Phase 2 gap #3](#3-ocr-path-disabled).

---

## Pipeline stages

Blob upload → Event Grid → Durable orchestrator. Each step writes its artifact
to `processing/{doc_id}/{run_id}/`, so any stage is independently inspectable
(`demo.py pull` downloads all of them at once).

| Step | Does | Artifact |
|---|---|---|
| 1 | pre-analysis — page count, text presence | `step1-result.json` |
| 2 | ADI `prebuilt-layout` + **normalization** | `adi-raw.json`, `adi-content.md` |
| 3 | confidence routing — which pages need a second read | `routing.json` |
| 4 | OCR enrichment *(disabled)* | `mistral-page-N.md` |
| 4A | crop each detected figure from the page | `figures.json` |
| 4B | qualify — geometry-only reject of page furniture | `figures.json` |
| **4C** | **🔮 calls the vision model** (`gpt-4o-mini`) on survivors only | `figure-understanding.json` |
| 5 | chunk composition — see [CHUNKING.md](CHUNKING.md) | `chunks.json` |
| 6 | embedding | `chunks-embedded.json` |
| 7 | index upsert | `step7-result.json` |

**This is the only step in the whole pipeline that calls a vision model.**
Steps 1–3 and 5–7 are deterministic code; step 4 (OCR) is disabled. If you're
looking for "where is AI actually used here" — it's step 4C, and its full
design (prompt, schema, qualification funnel, cost controls) is in
[figure-understanding-extension.md](figure-understanding-extension.md), not
repeated here.

`doc_id = sha256(content)[:16]` — **content only, not filename**. Re-uploading
identical bytes under a new name resolves to the same document rather than
duplicating it. (Caveat in [Phase 2 gap #5](#5-docid-ignores-filename).)

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
cheap reader admitted weakness. This is the same design principle that shows up
again inside figure understanding — see
[why qualification happens before any vision call](figure-understanding-extension.md).

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
snake_case. Each lookup returned `None`, masked by an `or 1` default. The
result: **every citation in the system reported page 1**, silently, from day
one.

The failure mode is the point. Nothing crashed; answers looked correct; only the
provenance was wrong — the one thing the system exists to guarantee. Fixed by
normalizing at write *and* on read (so existing artifacts self-repair), pinned by
13 regression tests in `tests/unit/test_adi_normalize.py`.

---

## Phase 2 — known gaps

Deliberate limitations, not oversights. Each is a real lever with a real cost.

Two gaps that are specifically about the vision-model call live with
[figure understanding's own gap list](figure-understanding-extension.md#known-gaps)
instead of here, since fixing them means changing that prompt, not this
pipeline. Everything below is pipeline- or infrastructure-level.

### 1. No server-side vectorizer on the index

`vectorizers: []`, so the index cannot embed a query itself. Clients must supply
the vector — which `demo.py` does.

Consequence: **Azure AI Foundry's "add your data" cannot run vector search
against this index.** It fails outright, or worse, silently degrades to
keyword-only and quietly loses the semantic matching that makes figure retrieval
work. Full explanation in [DEMO.md](DEMO.md#why-the-demo-doesnt-use-foundrys-chat-ui).

**Fix:** attach an `azureOpenAI` vectorizer to the profile. ~20 minutes. Deferred
only because it touches a working index.

### 2. No relevance floor in retrieval

Search returns nearest neighbours regardless of quality, so a query nothing in
the corpus depicts still yields results. `demo.py figures` now reports cosine
similarity and warns below threshold (measured: unrelated ≈0.78, genuine ≥0.87),
but **the pipeline itself applies no floor.**

### 3. OCR path disabled

`OCR_ENABLED=false`. The router, merge logic, and normalization are implemented
and tested, but no Mistral OCR deployment is attached. Merged-cell tables and
low-confidence pages therefore keep ADI's best-effort output. See
[DEPLOYMENT.md → Enabling Mistral OCR later](../DEPLOYMENT.md#enabling-mistral-ocr-later).

### 4. Deferred test coverage

81 unit tests pass. OpenSpec tasks 3.6, 4.7 and 6.6 — figure qualification edge
cases — remain unwritten. Qualification was instead validated empirically across
330 real figures.

### 5. `doc_id` ignores filename

`sha256(content)[:16]`. Two filenames with identical bytes collapse to one
document, and deleting either removes both. Correct for dedup, surprising for
versioned files.

### 6. App Insights telemetry not flowing

Steps emit `step_start` / `step_end` / `step_error`, but traces are not reaching
App Insights. Diagnose via Durable storage tables meanwhile
(`DEPLOYMENT.md`). Cause is likely MCAPS policy-managed diagnostic settings.

---

## See also

- [README.md](../README.md) — capabilities, architecture, quick start
- [CHUNKING.md](CHUNKING.md) — how the three chunk types are built and why
- [figure-understanding-extension.md](figure-understanding-extension.md) — the vision-model call in full
- [DEPLOYMENT.md](../DEPLOYMENT.md) — infrastructure, settings, operations
- [DEMO.md](DEMO.md) — presenting the pipeline
