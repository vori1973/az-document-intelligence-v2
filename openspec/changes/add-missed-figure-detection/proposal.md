## Why

Step 4A only ever sees the figures Azure Document Intelligence reports, so a figure ADI never detects is invisible to the entire pipeline — it is not rejected, not counted, and not indexed. On the confirmed case (`162000-159772.pdf`, 16 pages), ADI reported 9 figures and none on pages 6 or 8, while both pages carry real embedded photographs covering roughly 64% and 44% of the page. `step4a-result.json` recorded `rejected: 0`, because there was never a candidate to reject.

Neither existing mechanism backstops this. The OCR second pass only runs on pages the confidence router flags, and routing keys entirely off table signals, so a page with no ADI table and no ADI figure never reaches it — and OCR merges its output by matching ADI's `figures[]` index, which has no slot on such a page. OCR improves reading a region ADI already found; it cannot supply a region ADI never found.

## What Changes

- Add a PyMuPDF pre-pass that enumerates the PDF's own embedded image placements per page, independently of ADI.
- Cross-check those placements against ADI's reported figure polygons and recover placements that overlap no ADI figure as additional figure candidates.
- Give every figure record a provenance field recording which detector produced it, so recovered figures are attributable and measurable.
- Derive a recovered figure's bounding polygon from the PDF's own placement rectangle, preserving exact-box citation quality rather than degrading to a page-level citation.
- Extend page classification to per-page granularity and skip the cross-check on scanned pages, where a single full-page raster is structurally indistinguishable from a deliberate full-bleed image.
- Reprocess the existing test corpus so previously missed figures are indexed.

## Capabilities

### New Capabilities
- `figure-detection-recovery`: Cross-checks the PDF's embedded image placements against the document reader's detected figures and recovers figures the reader missed, with recorded provenance and per-page gating.

### Modified Capabilities
- `figure-understanding`: Crops and qualification currently apply to "every figure Document Intelligence detects" and citations must originate from Document Intelligence. Both requirements change to admit recovered figures with PDF-derived polygons, while keeping the model non-authoritative for citations.

## Impact

- `src/activities/step1_preanalysis.py` and `PreAnalysisResult` — per-page text and image classification instead of one document-level `has_text` boolean.
- `src/activities/step4a_figures.py` — the cross-check, recovery, and provenance assignment.
- `src/models/types.py` — provenance field on figure records; per-page pre-analysis structure.
- `figures.json`, `step1-result.json`, and `step4a-result.json` artifact contents.
- Indexed figure chunks: documents already ingested must be reprocessed to pick up recovered figures.
- No new external dependency — PyMuPDF is already used by step 1 and step 4A.
