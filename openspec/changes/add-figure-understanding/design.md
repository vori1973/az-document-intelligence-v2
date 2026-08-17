## Context

See `proposal.md` — Why, and `docs/figure-understanding-extension.md` for the full background analysis.

Constraints that shape the approach:

- `step2_adi` already calls `begin_analyze_document(..., output=["figures"])`, so figure polygons, captions, and page numbers are already available in `adi-raw.json` and `adi-results.json`.
- The `document-chunks` index already carries `image_blob`, `figure_index`, and `bounding_polygon`. No index migration is available cheaply — the index has no vectorizer and embeddings are computed in step 6 at 1536 dimensions.
- ADI reports PDF geometry in **inches**; PyMuPDF operates in **points** (×72). Any polygon-to-pixel conversion must account for this.
- The existing AOAI resource has `gpt-4o-mini` (2024-07-18, GlobalStandard) deployed with substantial headroom. The Function App's managed identity already holds `Cognitive Services OpenAI User` for step 6 embeddings, and the same role covers chat completions.
- The orchestrator is Durable Functions; activity inputs and outputs must be JSON-serializable and activities must be individually retryable.

## Goals / Non-Goals

**Goals:**
- Never spend a vision call on something a cheap geometric test can reject.
- Make the figure's *visual* content the retrievable surface, without letting the model touch citation data.
- Degrade to current behavior when disabled or when any part of the new path fails.
- Keep per-document cost bounded and predictable.

**Non-Goals:**
- Multimodal/CLIP-style image embeddings. Text embeddings over a verbalization are enough for this capability and require no index change.
- Re-ranking, answer synthesis, or any change to query-time behavior.
- Changing the embedding model. Tracked separately.
- PDF object-layer (XObject) pre-pass analysis and cross-page boilerplate detection. Deferred; see Open Questions.

## Decisions

### Crop with PyMuPDF rather than ADI's figure retrieval API

ADI can return figure crops via `get_analyze_result_figure`, but PyMuPDF rendering was chosen:

- **DPI control.** Legible embedded text is the single biggest driver of vision quality. PyMuPDF renders at an arbitrary DPI; ADI returns a fixed-resolution crop.
- **No per-figure HTTP call.** A 40-figure document would mean 40 extra round trips.
- **No result TTL dependency.** ADI results expire; the source PDF and its stored artifacts do not, so a run can be re-cropped later from stored state.
- **Already a dependency.** PyMuPDF is used by `step4_ocr` for page extraction.

Citation authority is unaffected — the polygons still come from ADI. PyMuPDF only rasterizes.

*Alternative considered:* `get_analyze_result_figure`. Rejected on resolution and re-runnability, not correctness.

### Qualification is deterministic and runs before the model

The naive design lets the model decide what is meaningful. That pays a call for every rule, separator, and logo on every page.

Instead, geometry rejects the obvious cases first: header/footer overlap, area below/above bounds, and extreme aspect ratio. These are cheap, explainable, and tunable per corpus.

The important safeguard: **a hard rejection requires a geometric trigger AND the absence of any textual reference to the figure.** A caption, or an in-text mention on the same page ("see Figure 4", "shown below"), overrides geometry. This deliberately biases toward recall — a wasted vision call is cheap, a silently dropped figure is a retrieval hole nobody notices.

*Alternative considered:* model-decides-everything. Rejected on cost and on the inability to explain a rejection.

### One combined call, not classify-then-describe

A two-call design (is it meaningful? → describe it) doubles cost and creates a class of bug where the two calls disagree. A single schema-enforced call returns `is_meaningful` alongside the description; the description is simply ignored when the figure is rejected.

Structured Outputs (`response_format: json_schema`, `strict: true`) is used so a malformed response is impossible rather than merely unlikely. `temperature=0` for reproducibility.

### Rejection requires confidence; uncertainty retains

Routing on the model's verdict:

| Model verdict | Outcome |
|---|---|
| `is_meaningful=false` AND confidence `high` | reject |
| `is_meaningful=true` | retain and index |
| not meaningful, but confidence `medium`/`low` | retain |
| call failed or schema violation | retain, no description |

Only a *confident* negative removes a figure. Everything else survives, matching the same recall bias as 4B.

Confidence is a categorical label (`high`/`medium`/`low`), not a number, because a self-reported numeric probability from an LLM is not calibrated and invites false precision.

### Verbalization is composed into the embedded text, not stored separately

The description, visible labels, component terms, warnings, and search keywords are concatenated into `text_for_embedding` alongside the original caption. This means figures become retrievable through the existing text-embedding path with **zero index schema change** — the single most important property for shipping this quickly.

The raw structured output is also persisted as a run artifact for debugging and for future re-use without re-calling the model.

### Step 4C is skipped when 4B qualifies nothing

The orchestrator inspects 4A's result and only calls 4C when at least one candidate survived. A document with no meaningful figures costs nothing beyond the crop attempt.

### Concurrency, caps, and configuration

Vision calls run in a bounded thread pool (`FIGURE_MAX_CONCURRENT`, default 4) to keep wall time reasonable without tripping rate limits; 429/503 responses retry with backoff. `FIGURE_MAX_PER_DOC` (default 60) caps worst-case spend on a figure-dense document.

All 4B thresholds are environment-configurable so the filter can be tuned per corpus without a code change.

## Risks / Trade-offs

- **Inch/point unit confusion produces silently wrong crops** → Conversion is centralized in one place; validated by eye against a known figure-rich PDF before demo.
- **Over-aggressive 4B silently drops real figures** → Rejections require a geometric trigger *and* no textual reference; thresholds are configurable; 4A persists rejected candidates with their rejection reason so the filter is auditable.
- **Model hallucinates device identity, measurements, or warnings** → Explicit grounding prohibitions in the system prompt; unreadable text must be declared in `uncertainty`. The output is retrieval metadata only and is never presented as source text.
- **Vision latency dominates pipeline time on figure-dense documents** → Bounded parallelism plus a per-document cap. The activity is separately retryable, so a failure does not re-run ADI.
- **Verbalization dilutes the embedding for figures with a strong caption** → The caption is always retained at the front of the composed text.
- **Cost scales with figure count** → Deterministic pre-filtering plus `FIGURE_MAX_PER_DOC`; `gpt-4o-mini` is the cheapest vision-capable option available on the existing resource.

## Migration Plan

1. Deploy code with `FIGURE_UNDERSTANDING_ENABLED=false` — behavior is identical to today.
2. Set `FIGURE_UNDERSTANDING_MODEL` and enable the flag.
3. Re-ingest a figure-rich document and inspect the 4A/4C run artifacts before trusting the index.

**Rollback:** set `FIGURE_UNDERSTANDING_ENABLED=false`. Figure chunks revert to caption-only text on the next ingest; no index schema change means no rollback migration.

Note: re-ingesting an already-processed PDF with unchanged content is skipped by design (document identity is content-derived). Forcing reprocessing requires clearing that document's name-index entry.

## Open Questions

- Should repeated-boilerplate detection (the same figure appearing at the same position across many pages) be added to 4B? It is the one rejection rule from the design doc not implemented, and it needs cross-page state that the current per-page qualification does not carry. Deferrable: its absence costs a few extra vision calls, not correctness.
- Whether a padded "context crop" retry is worth implementing for figures where the model sets `needs_larger_context_crop`. The flag is captured today but not acted on.
- Whether the header/footer overlap signal should be split into separate header and footer ratios. Currently merged; the rejection logic is unaffected.
