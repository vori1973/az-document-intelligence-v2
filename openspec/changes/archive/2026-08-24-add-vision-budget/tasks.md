## 1. Budget derivation

- [x] 1.1 Replace `MAX_FIGURES` in `src/activities/step4c_understanding.py` with `FIGURE_PER_PAGE_ALLOWANCE` (default `4`) and `FIGURE_MAX_PER_DOC_CEILING` (default `500`)
- [x] 1.2 Derive the budget as `min(page_count * allowance, ceiling)`, sourcing page count from the 4A result rather than recomputing it
- [x] 1.3 Unit test: budget scales with pages, clamps at the ceiling, and handles a single-page document

## 2. Page-balanced selection

- [x] 2.1 Replace the `[:MAX_FIGURES]` slice at line ~201 with round-robin selection: group qualified figures by page, order each page's figures by descending area, then take one per page in page order, cycling until the budget is exhausted
- [x] 2.2 Preserve page order in the emitted result so downstream consumers and `figures.json` remain page-ordered
- [x] 2.3 Unit test: when the budget binds, every page with qualified figures contributes at least one figure and no contiguous page range is wholly absent
- [x] 2.4 Unit test: when the budget does not bind, every qualified figure is analyzed and ordering is unchanged from today

## 3. Truncation telemetry

- [x] 3.1 Add `qualified_count`, `budget`, `analyzed_count`, `budget_bound` to the 4C result model in `src/models/types.py`
- [x] 3.2 Populate them in `step4c_understanding.py` and include them in `step4c-result.json`
- [x] 3.3 Emit a warning-level log line when `budget_bound` is true, naming the qualified and analyzed counts
- [x] 3.4 Unit test: the fields are present and correct in both the binding and non-binding cases

## 4. Placeholder chunk suppression

- [x] 4.1 In `src/activities/step5_chunks.py`, skip emitting a figure chunk when the figure has neither a vision description nor a caption
- [x] 4.2 Confirm a figure with a caption but no description still indexes on caption text, preserving the documented degraded mode
- [x] 4.3 Unit test: no chunk for description-less and caption-less figures; caption-only figures still produce a chunk
- [x] 4.4 Verify against the technique guide run, where 102 of 177 figure chunks are currently `"[Figure]  (Page N)"` placeholders

  Confirmed via live deployment: previously 102/177 figure chunks were empty
  placeholders. Re-run under this change produces 176 figure chunks, **0**
  placeholders — every analyzed figure indexes with a real description.

## 5. Model tiering

- [x] 5.1 Add `FIGURE_MODEL_PREMIUM`, `FIGURE_MODEL_ECONOMY`, and `FIGURE_PREMIUM_MAX_FIGURES` (default `60`), keeping existing `FIGURE_MODEL` behavior as the default for both tiers
- [x] 5.2 Select the model once per document from the analyzed figure count and record the choice in the step result
- [x] 5.3 Unit test: selection at, below, and above the threshold; identical tiers produce no observable tiering

## 6. Validation

- [x] 6.1 Run `.venv/bin/python -m pytest tests/ -q`
- [x] 6.2 Re-run the technique guide and confirm figures are described past page 22 and placeholder chunks are gone

  Confirmed via live deployment: `step4c-result.json` reports
  `qualified_count: 179, analyzed_count: 179, budget: 288, budget_bound: false`
  (174 retained, 2 retain_unverified, 1 retain_low_confidence, 2 rejected).
  Figure chunks span pages 4-71 (46 chunks past page 22, previously empty
  under the old cap), zero placeholder chunks.
- [x] 6.3 Re-run the product catalog and confirm all 195 qualified figures are analyzed and `budget_bound` is false

  Confirmed via live deployment (`docintv2-dev-rg`): `step4c-result.json` reports
  `qualified_count: 195, analyzed_count: 195, budget_bound: false` (191 retained,
  4 rejected as out-of-scope). `chunks.json` contains 191 figure chunks, zero of
  which are empty placeholders (`"[Figure]  (Page N)"`).
- [x] 6.4 Confirm orchestrator activity timeouts tolerate the ceiling case, since 4C wall-clock grows with analyzed count

  `src/host.json` allows 30 minutes. Measured live: 195 figures at concurrency 4
  took 134.3s wall-clock (`step4c-result.json` `duration_ms: 134319`).
  Extrapolating linearly, the 500-figure ceiling would take roughly 5.7 minutes,
  still well within the 30-minute activity timeout.
- [x] 6.5 Record measured cost and wall-clock for both documents in the change folder before archiving

  **Product catalog** (159 pages, 195 qualified figures, model `gpt-4o-mini`):
  134.3s wall-clock for figure understanding; cost ≈ 195 × $0.0023 ≈ **$0.45**,
  matching the design doc's estimate. Full artifacts in
  `demo-assets/output/DPS Sports Medicine Product Catalog v1.2 April 2023/`.

  **Technique guide** (72 pages, 179 qualified figures, model `gpt-4o-mini`):
  131.9s wall-clock for figure understanding; cost ≈ 179 × $0.0023 ≈ **$0.41**.
  All 179 figures analyzed (`budget_bound: false`), figure chunks span pages
  4-71 (previously cut off at page 22), zero placeholder chunks.

  **Technique guide**: pending — re-run and record before archiving.
