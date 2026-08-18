# Chunking Strategy — Turning Extracted Content Into Retrievable Facts

How step 5 turns ADI's output (plus the vision model's figure descriptions)
into search index documents. This is the "table normalization" concept: three
chunk types, each shaped for a different kind of question.

Pipeline context (where step 5 sits, what feeds it) is in
[PIPELINE.md](PIPELINE.md). How figure descriptions are generated (the vision
model call) is in
[figure-understanding-extension.md](figure-understanding-extension.md) — this
document only covers the chunk *shape* that results, not how the text inside
it was produced.

The goal: **every chunk is independently answerable with an exact citation.**

<details>
<summary>Diagram — a 3-page PDF decomposed into chunks (click to expand)</summary>

<img src="diagrams/pdf-chunking-strategy.drawio.svg" width="900"
     alt="PDF chunking strategy — a 3-page PDF decomposed into paragraph, table-row and figure chunks"/>

</details>

---

## Table of contents

- [Table row chunks](#table-row-chunks-one-row-per-chunk)
- [ADI/OCR merge and cell-grid normalization](#adiocr-merge-and-cell-grid-normalization)
- [Paragraph chunks](#paragraph-chunks)
- [Figure chunks](#figure-chunks)
- [Why three types, retrieved together](#why-three-types-retrieved-together)

---

## Table row chunks — one row per chunk

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
topic, so a numeric query competes against noise; without headers the values
are unretrievable; and citation granularity collapses to page level, losing the
row polygon needed to highlight the exact cell.

**Why not one chunk per table?** Same problems at larger scale. A 50-row table
averages its vector across unrelated categories, forces the LLM to scan
everything to read one fact, and overflows `CHUNK_TOKENS` — requiring either
truncation (silent data loss) or a bigger window (further dilution). Row-level
chunking scales uniformly: a 5-row and a 500-row table produce chunks of
identical size and identical retrieval precision — each chunk is a single,
independently retrievable fact.

Two details that matter for ranking:

- **Table label prefix** — every row is prefixed `Table: <label>`, where label
  is the caption or, failing that, the normalized column headers
  (`Color | State | Description`). Computed once and reused verbatim in the
  paragraph pointer (below), so the two always match.
- **Lead-in context** — the last 1–2 sentences of the nearest preceding prose
  paragraph on the same page are prepended as `Context: …`, anchoring rows to
  topical wording that never appears in the cells (e.g. *"The Header displays
  user instructions. The following color-code is used within the Header:"*).
  Must exceed `CHUNK_LEAD_IN_MIN_CHARS` (default 30) to exclude UI labels and
  lone numbers.

---

## ADI/OCR merge and cell-grid normalization

Before a table becomes `table_row` chunks, its cells go through span
resolution, then (when OCR is enabled) a routing decision between ADI's and
OCR's reading of the same table. This logic is ported unchanged from v1 and
lives in `step5_chunks.py`; **all of it runs even while OCR is disabled** —
merged-cell resolution is not an OCR feature, only the routing choice is.

**1. Cell-grid resolution (`_build_adi_cell_grid`)** — ADI reports merged
cells as one cell with a `row_span`/`column_span`; chunking needs a flat
per-cell grid. Each spanning cell's content is copied into every `(row, col)`
position it covers, and non-origin span rows are marked so later passes can
tell "genuinely empty" apart from "empty because it's mid-span."

**2. Implicit row-span fill (`_normalize_adi_grid`)** — ADI sometimes detects
the row-span on the label column but not on the value columns next to it, so
values end up on only one row instead of every row in the visual group. For
each run of rows sharing the same label, if exactly one row in the run has a
non-empty value, that value is propagated to the rest of the run; if multiple
rows disagree, they're left alone as genuine per-row data. Runs on **every**
table, ADI-only or OCR, and is the input both paths chunk from.

**3. ADI-vs-OCR routing** (only matters once
[OCR is enabled](PIPELINE.md#3-ocr-markdown-the-second-reader-currently-disabled)):
compares Mistral's data-row count against ADI's; a mismatch, a table with 3+
header rows (OCR sub-headers would be miscounted as data), or ADI reporting
very low cell confidence with zero OCR tables on the page (`image_artifact` —
ADI likely mistook a chart/photo for a table) all fall back to
`_normalize_adi_grid`'s output instead of trusting OCR.

**4. OCR two-pass fill** (`_normalize_mistral_table`, OCR path only) — OCR
tables need their own merge recovery, done as fill-right then fill-down
*in that order* (row spans overwrite blanks that a later fill-right check
depends on): fill-right restores column-span fragments split by ADI
(`"300 Cases"` split into `"300"` + `""`), fill-down restores row-span
values using ADI's grid as an override when the OCR model splits one
merged cell's text across multiple rows instead of repeating it.

Every table's routing decision and flags (`row_count_mismatch`,
`mistral_multi_header`, `image_artifact`, `high_empty_ratio`) are written to
`tables-flags.md`/`tables-stats.md` alongside the run so a low-confidence
table can be traced back to the specific rule that chose its source — see
[DEMO.md](DEMO.md) for pulling these diagnostics for a real run.

---

## Paragraph chunks

Paragraph blocks from ADI, split at ~500 tokens with ~100 token overlap
(`CHUNK_TOKENS` / `CHUNK_OVERLAP_TOKENS`). Three pre-processing passes run
before chunking:

1. **Role filtering** — paragraphs with ADI roles `pageHeader`, `pageNumber`,
   and `pageFooter` are excluded. Running document titles repeat on every page
   and dilute embeddings toward the document topic rather than the paragraph's
   specific content; bare page numbers and footers add meaningless tokens.

2. **Table cell exclusion** — ADI duplicates every table cell into
   `paragraphs[]` alongside `tables[].cells[]`. Without filtering, these appear
   as flat, column-context-free noise inside paragraph chunks (e.g.
   `"0\n0.0335\n-0.939\n3e-4"`) while the same data is already captured —
   correctly structured — in `table_row` chunks. Each contiguous run of
   table-cell paragraphs is replaced by a single inline pointer
   `[Table: <label>]`, using the identical label computed for the row prefix
   above, so the LLM knows structured data is available and what its columns
   are even when no formal caption exists.

3. **Checkbox artefact normalisation** — ADI's form-recognition emits
   `:selected:` / `:unselected:` markers (e.g. UI button state descriptions).
   Replaced with `[checked]` / `[unchecked]` so the sentence stays readable
   without garbage tokens in the embedding.

Kept roles: `body`, `sectionHeading`, `title` — these carry genuine content and
retrieval value.

```json
{
  "chunk_id": "5746428c_p7_para2",
  "type": "paragraph",
  "text_for_embedding": "The plot of inhibitor concentration over degree of surface coverage...",
  "citation": { "page": 7, "bounding_polygon": [...] }
}
```

---

## Figure chunks

One chunk per **qualified** figure (qualification happens in step 4B, before
this step ever sees it — see
[figure-understanding-extension.md](figure-understanding-extension.md)).

```json
{
  "chunk_id": "5746428c_p7_fig0",
  "type": "figure",
  "text_for_embedding": "Figure: Figure 3. Implant planning and balance graph for mechanical alignment. The balance curve shows the TKA will be too tight medially in extension (measured 9mm, target 12mm)...",
  "image_blob": "figures/p7-fig0.png",
  "citation": { "page": 7, "figure_index": 0, "bounding_polygon": [...] }
}
```

The critical design choice: `text_for_embedding` is the **vision model's
generated description**, not the ADI caption. That is what makes
*"balance graph showing knee alignment gaps"* retrieve a chart whose caption
never uses those words — the embedding is built from what the image *shows*,
not what it's labeled.

This document stops at the chunk shape. How that description text is produced
— the crop, the qualification funnel, the vision prompt and schema, and its
known accuracy gap — is a separate concern:
[figure-understanding-extension.md](figure-understanding-extension.md).

---

## Why three types, retrieved together

`table_row`, `paragraph`, and `figure` chunks answer different *shapes* of
question and are designed to be retrieved side by side in the same query:

| Chunk type | Answers |
|---|---|
| `table_row` | *"What is X at Y?"* — a lookup |
| `paragraph` | *"Why does X happen?"* — an explanation |
| `figure` | *"What does the [image] show?"* — something never in the text at all |

The `[Table: <label>]` pointer in paragraph chunks signals to the LLM that
structured data exists nearby, and with a sufficient `QUERY_TOP_K` all three
types can appear in the same context window for one question.

---

## See also

- [PIPELINE.md](PIPELINE.md) — where step 5 sits in the overall pipeline, and the Phase 2 gap list
- [figure-understanding-extension.md](figure-understanding-extension.md) — how figure descriptions are generated
- [DEMO.md](DEMO.md) — seeing these chunks live against real documents
