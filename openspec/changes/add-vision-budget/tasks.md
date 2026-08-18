## 1. Budget derivation

- [ ] 1.1 Replace `MAX_FIGURES` in `src/activities/step4c_understanding.py` with `FIGURE_PER_PAGE_ALLOWANCE` (default `4`) and `FIGURE_MAX_PER_DOC_CEILING` (default `500`)
- [ ] 1.2 Derive the budget as `min(page_count * allowance, ceiling)`, sourcing page count from the 4A result rather than recomputing it
- [ ] 1.3 Unit test: budget scales with pages, clamps at the ceiling, and handles a single-page document

## 2. Page-balanced selection

- [ ] 2.1 Replace the `[:MAX_FIGURES]` slice at line ~201 with round-robin selection: group qualified figures by page, order each page's figures by descending area, then take one per page in page order, cycling until the budget is exhausted
- [ ] 2.2 Preserve page order in the emitted result so downstream consumers and `figures.json` remain page-ordered
- [ ] 2.3 Unit test: when the budget binds, every page with qualified figures contributes at least one figure and no contiguous page range is wholly absent
- [ ] 2.4 Unit test: when the budget does not bind, every qualified figure is analyzed and ordering is unchanged from today

## 3. Truncation telemetry

- [ ] 3.1 Add `qualified_count`, `budget`, `analyzed_count`, `budget_bound` to the 4C result model in `src/models/types.py`
- [ ] 3.2 Populate them in `step4c_understanding.py` and include them in `step4c-result.json`
- [ ] 3.3 Emit a warning-level log line when `budget_bound` is true, naming the qualified and analyzed counts
- [ ] 3.4 Unit test: the fields are present and correct in both the binding and non-binding cases

## 4. Placeholder chunk suppression

- [ ] 4.1 In `src/activities/step5_chunks.py`, skip emitting a figure chunk when the figure has neither a vision description nor a caption
- [ ] 4.2 Confirm a figure with a caption but no description still indexes on caption text, preserving the documented degraded mode
- [ ] 4.3 Unit test: no chunk for description-less and caption-less figures; caption-only figures still produce a chunk
- [ ] 4.4 Verify against the technique guide run, where 102 of 177 figure chunks are currently `"[Figure]  (Page N)"` placeholders

## 5. Model tiering

- [ ] 5.1 Add `FIGURE_MODEL_PREMIUM`, `FIGURE_MODEL_ECONOMY`, and `FIGURE_PREMIUM_MAX_FIGURES` (default `60`), keeping existing `FIGURE_MODEL` behavior as the default for both tiers
- [ ] 5.2 Select the model once per document from the analyzed figure count and record the choice in the step result
- [ ] 5.3 Unit test: selection at, below, and above the threshold; identical tiers produce no observable tiering

## 6. Validation

- [ ] 6.1 Run `.venv/bin/python -m pytest tests/ -q`
- [ ] 6.2 Re-run the technique guide and confirm figures are described past page 22 and placeholder chunks are gone
- [ ] 6.3 Re-run the product catalog and confirm all 195 qualified figures are analyzed and `budget_bound` is false
- [ ] 6.4 Confirm orchestrator activity timeouts tolerate the ceiling case, since 4C wall-clock grows with analyzed count
- [ ] 6.5 Record measured cost and wall-clock for both documents in the change folder before archiving
