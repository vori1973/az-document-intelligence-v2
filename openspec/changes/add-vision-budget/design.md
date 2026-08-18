## Context

4C caps analysis at `FIGURE_MAX_PER_DOC`, default 60, applied as a slice over figures already sorted by page. The value predates any measurement of figure density and was chosen to bound cost on an unknown corpus.

Measurements from the eight pulled runs:

| document | pages | qualified | density | `pages*4` |
|---|---|---|---|---|
| single-page datasheet | 1 | 2 | 2.00 | 4 |
| clinical study | 6 | 11 | 1.83 | 24 |
| clinical reference | 14 | 9 | 0.64 | 56 |
| hardware factsheet | 3 | 4 | 1.33 | 12 |
| patient brochure | 4 | 4 | 1.00 | 16 |
| hardware catalog | 19 | 36 | 1.89 | 76 |
| technique guide | 72 | 179 | 2.49 | 288 |
| product catalog | 159 | 195 | 1.23 | 500 |

Peak observed density is 2.49 qualified figures per page.

## Goals / Non-Goals

**Goals.** Make the budget fit the document. Make truncation uniform and observable. Stop emitting index entries for figures that were never analyzed.

**Non-Goals.** Changing which figures qualify — that is `fix-figure-qualification-thresholds`. Recovering figures ADI never detected — that is `add-missed-figure-detection`. Changing crop rendering or the vision prompt.

## Decisions

### Budget = `min(pages * 4, 500)`

Per-page because density is a document property; a constant is simultaneously too small for a catalog and far larger than a 3-page factsheet needs.

The multiplier is 4 against a peak observed density of 2.49, a headroom factor of 1.6. That headroom is deliberate: `fix-figure-qualification-thresholds` raises qualified counts (product catalog 195 → 257, density 1.23 → 1.62), and the budget must not silently absorb that change. At 4/page every document in the corpus fits its budget both before and after that change, so the budget stops being a variable in figure-recall behavior.

The 500 ceiling is a runaway-cost stop for pathological input, not a shaping parameter. At roughly $0.0023 per figure it bounds a single document near $1.15. product catalog post-threshold-change sits at 257, comfortably under.

Rejected alternatives:

- **Raise the fixed cap to 300.** Still arbitrary, still wrong at both ends, and still binds on the two documents that matter.
- **No cap.** A corrupt or adversarial PDF reporting thousands of figures becomes an unbounded spend with no circuit breaker.
- **Budget by qualified count rather than pages.** Circular — qualification is what the budget is meant to be independent of, and it would let a qualification regression quietly inflate cost.

### Spend the budget round-robin by page

Take the largest unanalyzed figure from each page in turn, cycling until the budget is exhausted. Within a page, larger figures go first as a proxy for prominence.

The current failure is not that some figures are dropped but that the dropped ones are contiguous and always at the end. the technique guide's pages 1–21 are fully described and 22–72 are empty. Round-robin converts "the second half of the document does not exist" into "every page is represented, dense pages less completely" — a degradation that is uniform, predictable, and leaves no region of the document unretrievable.

This matters most where the budget is tightest, which is exactly where a reader is least able to notice the loss.

### Suppress chunks for unanalyzed figures

A figure with neither description nor caption currently indexes as `"[Figure]  (Page 22)"` — 102 such chunks in the technique guide alone. These match no meaningful query, occupy index space, and cluster as near-identical low-information vectors.

The existing baseline requirement already states that qualification "governs index contents and not merely the vision budget"; placeholder chunks violate it. A figure with a real caption but no description still indexes on its caption, which is the documented degraded mode and is unchanged.

### Report when the budget binds

Emit qualified count, budget, analyzed count, and a `budget_bound` flag in the 4C step result. Truncation is currently indistinguishable from a document that simply has few figures.

This is also the tuning signal: if `budget_bound` is routinely true, the correct response is usually to investigate qualification rather than to raise the budget, since a document exceeding 4 figures per page is more likely over-qualifying noise than genuinely that dense.

### Per-document model selection

Allow a more capable model below a configured figure count, a cheaper one above.

The marginal value of description accuracy falls as figure count rises while its marginal cost rises. On an 11-figure factsheet one poor description is roughly 9% of that document's figure retrievability; on a 257-figure catalog it is 0.4%. Corpus cost with a premium tier at 60 figures is about $1.38 against $1.22 for uniformly cheap — a small premium concentrated where it changes outcomes.

Kept as configuration rather than fixed policy; the default may be a single model for both tiers.

## Risks / Trade-offs

- **Cost rises roughly 2.2×** (about $0.55 → $1.22 for the corpus). Bounded per document by the ceiling and observable via the new telemetry. This is the intended purchase: 254 figures currently paid for in qualification but discarded before analysis.
- **Latency rises on large documents.** 4C is already concurrent (`MAX_CONCURRENT=4`); a 195-figure document is roughly 3× the vision wall-clock of a 60-figure one. Orchestrator activity timeouts should be checked against the ceiling case.
- **Figure chunk counts fall** on truncated documents even while described-figure counts rise. Expected, and the reason the two numbers are reported separately.
- **Round-robin changes which figures are analyzed** when the budget binds, so re-running a previously truncated document produces a different described set rather than a superset. Acceptable — the budget binds on no document in the current corpus.

## Migration

Threshold changes only; no state migration. Previously ingested documents keep their existing chunks until reprocessed, including any placeholder chunks, which are removed on reindex.
