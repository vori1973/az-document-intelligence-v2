## 1. Data models and configuration

- [x] 1.1 Add `FigureFeatures` and `FigureCandidate` models to `src/models/types.py`
- [x] 1.2 Define 4B threshold configuration with defaults (`FIGURE_HEADER_FOOTER_OVERLAP_THRESHOLD`, `FIGURE_MIN_AREA_RATIO`, `FIGURE_MAX_AREA_RATIO`, `FIGURE_MAX_ASPECT_RATIO`)
- [x] 1.3 Define runtime configuration (`FIGURE_UNDERSTANDING_ENABLED`, `FIGURE_UNDERSTANDING_MODEL`, `FIGURE_CROP_DPI`, `FIGURE_MAX_CONCURRENT`, `FIGURE_MAX_PER_DOC`)
- [ ] 1.4 Declare the new app settings in `infra/modules/functions.bicep` so they are not deployment drift

## 2. Step 4A — figure cropping

- [x] 2.1 Convert ADI polygons (inches) to PyMuPDF rects (points) and crop at the configured DPI
- [x] 2.2 Upload each crop as a run artifact under a `figures/` prefix keyed by page and figure index
- [x] 2.3 Tolerate per-figure crop failure without failing the activity
- [ ] 2.4 Verify crops visually against a known figure-rich PDF to confirm the unit conversion is correct

## 3. Step 4B — deterministic qualification

- [x] 3.1 Compute per-figure features: area ratio, aspect ratio, header/footer overlap
- [x] 3.2 Implement textual-reference detection (caption present, or in-text figure reference on the same page)
- [x] 3.3 Implement the four hard rejection rules, each requiring a geometric trigger AND no textual reference
- [x] 3.4 Persist all candidates — retained and rejected, with reasons — to `figures.json`
- [x] 3.5 Write `step4a-result.json` per the existing step-result-files capability
- [ ] 3.6 Unit-test the qualification rules, including the reference-overrides-geometry case

## 4. Step 4C — vision understanding

- [x] 4.1 Define the controlled taxonomy and the strict JSON schema for structured output
- [x] 4.2 Write the grounding-constrained system prompt (no invented identity, measurements, warnings, or component names; unreadable text declared)
- [x] 4.3 Issue one schema-enforced `gpt-4o-mini` vision call per qualified candidate using managed identity
- [x] 4.4 Bound concurrency and retry transient failures with backoff
- [x] 4.5 Apply the routing outcome table — only a confident negative rejects
- [x] 4.6 Persist `figure-understanding.json` and `step4c-result.json`
- [ ] 4.7 Unit-test the routing outcome mapping across all verdict combinations

## 5. Orchestration

- [x] 5.1 Register `step4a_figures` and `step4c_understanding` as activities in `src/function_app.py`
- [x] 5.2 Call 4A after step 3 in the orchestrator with the standard retry policy
- [x] 5.3 Call 4C only when 4A qualified at least one candidate and the feature flag is on
- [x] 5.4 Update the orchestrator's documented activity sequence

## 6. Chunk composition

- [x] 6.1 Load `figure-understanding.json` in step 5, tolerating its absence
- [x] 6.2 Compose figure `text_for_embedding` from caption plus description, labels, component terms, warnings, and keywords
- [x] 6.3 Drop figure chunks whose routing outcome is a confident rejection
- [x] 6.4 Carry the tight crop URI into `image_blob`
- [x] 6.5 Preserve caption-only behavior when understanding is unavailable
- [ ] 6.6 Unit-test the composed text for both the enriched and fallback paths

## 7. Deployment and validation

- [ ] 7.1 Set the new app settings on the Function App
- [ ] 7.2 Deploy and confirm the two new activities are registered
- [ ] 7.3 Ingest a figure-rich PDF and inspect `figures.json`, `figure-understanding.json`, and the step result files
- [ ] 7.4 Confirm indexed figure chunks carry an enriched `text_for_embedding`, a crop reference, and an ADI-derived page and polygon
- [ ] 7.5 Run a retrieval query that finds a figure by its visual content rather than its caption
- [ ] 7.6 Confirm the full unit test suite still passes
