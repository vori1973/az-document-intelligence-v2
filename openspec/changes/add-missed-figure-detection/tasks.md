## 1. Data models and configuration

- [ ] 1.1 Add a per-page classification structure to `src/models/types.py` carrying page number, text presence, embedded image coverage ratio, and whether the page is eligible for the cross-check
- [ ] 1.2 Extend `PreAnalysisResult` with the per-page list, keeping the existing document-level `has_text` field intact for current consumers
- [ ] 1.3 Add a detection provenance field to `FigureCandidate` and to `FigureLocation`, defaulting to reader provenance so existing artifacts deserialize unchanged
- [ ] 1.4 Define configuration with defaults: `FIGURE_RECOVERY_ENABLED` (default off), `FIGURE_RECOVERY_OVERLAP_THRESHOLD`, `FIGURE_SCANNED_PAGE_COVERAGE_THRESHOLD`
- [ ] 1.5 Declare the new app settings in `infra/modules/functions.bicep` so they are not deployment drift

## 2. Step 1 — per-page enumeration and classification

- [ ] 2.1 Enumerate embedded raster placements per page with `get_images(full=True)` and `get_image_rects()`, recording page number, placement rectangle, and pixel dimensions
- [ ] 2.2 Compute per-page text presence and total image coverage ratio, and derive cross-check eligibility from the coverage threshold
- [ ] 2.3 Tolerate per-page enumeration failure without failing the activity, recording the page as not enumerable
- [ ] 2.4 Persist the placements and per-page classification so step 4A can consume them without reopening the PDF for enumeration
- [ ] 2.5 Keep `step1-result.json` backward compatible and confirm existing consumers still read it

## 3. Step 4A — cross-check and recovery

- [ ] 3.1 Convert placement rectangles from PyMuPDF points to the inch coordinate space ADI polygons use
- [ ] 3.2 Compute overlap between each placement and the ADI figure polygons on the same page, suppressing placements that substantially overlap an already-detected figure
- [ ] 3.3 Build figure candidates from unmatched placements on eligible pages, deriving the bounding polygon from the placement rectangle
- [ ] 3.4 Assign recovered figures figure indices that cannot collide with ADI-assigned indices
- [ ] 3.5 Skip the cross-check entirely on pages the step 1 classification marked ineligible
- [ ] 3.6 Run recovered candidates through the existing 4B qualification and cropping unchanged
- [ ] 3.7 Set provenance on every candidate and report recovered counts in `step4a-result.json`
- [ ] 3.8 Honor `FIGURE_RECOVERY_ENABLED`, falling back to reader-only behavior when disabled or when placements are unavailable

## 4. Downstream propagation

- [ ] 4.1 Carry provenance through `figures.json` into `figure-understanding.json` records
- [ ] 4.2 Confirm recovered figures reach step 4C and are described by the same vision call as reader-detected figures
- [ ] 4.3 Confirm figure chunks built from recovered figures carry the placement-derived polygon and the crop reference

## 5. Tests

- [ ] 5.1 Unit-test the points-to-inches conversion and the placement-to-polygon derivation
- [ ] 5.2 Unit-test overlap matching: exact match, substantial overlap, partial overlap below threshold, and no overlap
- [ ] 5.3 Unit-test per-page gating for a scanned page, a partial-coverage page, and a mixed document
- [ ] 5.4 Unit-test figure index assignment for collision-freedom against ADI indices
- [ ] 5.5 Unit-test provenance assignment and the disabled-recovery fallback path
- [ ] 5.6 Confirm the full unit suite still passes

## 6. Deployment and validation

- [ ] 6.1 Set the new app settings on the Function App and deploy
- [ ] 6.2 Ingest a 16-page clinical reference with recovery enabled and confirm pages 6 and 8 produce recovered figures with real polygons
- [ ] 6.3 Confirm previously detected figures on that document are unchanged, not duplicated, and still attributed to reader provenance
- [ ] 6.4 Verify crops of the recovered figures visually match the photographs on those pages
- [ ] 6.5 Run a retrieval query that finds a recovered figure by its visual content
- [ ] 6.6 Reprocess the remaining existing test documents, clearing their `processing/_name-index/` entries first so unchanged bytes are not skipped
- [ ] 6.7 Record recovery counts across the reprocessed corpus to quantify the detection gap

## 7. Documentation and spec hygiene

- [ ] 7.1 Update the known-gaps section in `docs/figure-understanding-extension.md` to reflect that the detection gap is now closed for digitally-born pages
- [ ] 7.2 Document the new configuration settings and the scanned-page limitation that remains
- [ ] 7.3 Update the `figure-understanding` capability Purpose directly in `openspec/specs/figure-understanding/spec.md` — a delta cannot carry it, because OpenSpec ignores `## Purpose` in a delta for an existing capability. The current sentence ends "...traceable to the exact page and bounding polygon reported by Azure Document Intelligence", which this change's MODIFIED requirements contradict once polygons can also come from the placement cross-check. Replace that clause with "...traceable to an exact page and bounding polygon produced by a deterministic detector rather than inferred by a model." Do this as part of implementation, not before: until recovery ships, the existing sentence is still accurate.
