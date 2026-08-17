## Why

The pipeline already detects figures via Azure Document Intelligence and emits one chunk per figure, but that chunk's embedded text is only `[Figure] {caption} (Page N)`. Figures whose captions are generic ("Figure 12") or absent are effectively unretrievable, and a figure carrying the answer — a labeled device component, a warning symbol, a procedure step — cannot be found by describing what it shows.

Technical and medical source documents put a large share of their meaning in figures. Without visual understanding, that content is indexed but not searchable, and the pipeline cannot answer "show me the handpiece connection port" with the image, page, and polygon that prove it.

## What Changes

- Add **step 4A** — crop every ADI-detected figure from the source PDF at a configurable DPI (default 200) using PyMuPDF, and upload each crop as a per-run artifact.
- Add **step 4B** — deterministic qualification that rejects page furniture (headers/footers, rules, separators, oversized background art) using geometry alone, before any model call is made. Every hard rejection requires both a geometric trigger and the absence of a textual reference to the figure.
- Add **step 4C** — one schema-enforced `gpt-4o-mini` vision call per surviving candidate, producing a controlled-taxonomy classification plus a grounded verbalization (description, visible labels, component terms, warnings, search keywords).
- Modify **step 5** so figure chunks embed the verbalization instead of the bare caption, and carry the tight crop URI as `image_blob`.
- Preserve ADI as the sole authority for citations: page, bounding polygon, and figure index are never model-derived.
- Skip step 4C entirely when 4B qualifies nothing, so documents without meaningful figures cost no vision tokens.
- Add configuration: `FIGURE_UNDERSTANDING_ENABLED`, `FIGURE_UNDERSTANDING_MODEL`, crop DPI, concurrency and per-document figure caps, and the 4B geometric thresholds.

## Capabilities

### New Capabilities
- `figure-understanding`: Cropping, deterministic qualification, and vision-based verbalization of document figures, plus the retrieval and citation contract for the resulting figure chunks.

### Modified Capabilities
<!-- None. `step-result-files` already requires each step to publish a result artifact; steps 4A and 4C follow that existing requirement without changing it. -->

## Impact

**New code**
- `src/activities/step4a_figures.py` — cropping + deterministic qualification
- `src/activities/step4c_understanding.py` — vision understanding

**Modified code**
- `src/orchestrators/pipeline_orchestrator.py` — 4A and conditional 4C between step 3 and step 5
- `src/function_app.py` — activity registration
- `src/activities/step5_chunks.py` — figure chunk text and `image_blob` composition
- `src/models/types.py` — `FigureFeatures`, `FigureCandidate`

**Infrastructure**
- Requires a vision-capable model deployment (`gpt-4o-mini`, GlobalStandard) on the existing Azure OpenAI resource. Already deployed; no new resource needed.
- New app settings on the Function App.
- The managed identity's existing `Cognitive Services OpenAI User` role covers the vision call — no new RBAC.

**Cost and latency**
- One vision call per qualified figure. Deterministic pre-filtering plus the per-document cap bound the spend; documents with no figures are unaffected.
- Adds one sequential activity to the pipeline; calls within 4C are parallel up to `FIGURE_MAX_CONCURRENT`.

**Search index**
- No schema change. `image_blob`, `figure_index`, and `bounding_polygon` already exist on `document-chunks`.

**Backward compatibility**
- Non-breaking. With `FIGURE_UNDERSTANDING_ENABLED=false`, or when the understanding artifact is absent, figure chunks fall back to the previous caption-only text.
