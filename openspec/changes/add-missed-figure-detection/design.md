## Context

Step 4A builds its candidate set solely from `adi-results.json`, so ADI's `figures[]` array is the pipeline's only source of figure existence. The confirmed failure on `162000-159772.pdf` is a detection gap, not a reading gap: ADI reported 9 figures and none on pages 6 or 8, while both pages carry embedded photographs (~64% and ~44% page coverage) on an unusually narrow 4in × 9in trim, bleeding slightly past the page edge.

PyMuPDF is already a dependency and is already opened twice in the pipeline — step 1 for the text heuristic and step 4A for cropping — so the enumeration itself costs no new dependency and no new document download. `step1-result.json` currently records `has_text` as a single document-level boolean.

See `proposal.md` for motivation, `specs/figure-detection-recovery/spec.md` for the new contract, and `specs/figure-understanding/spec.md` for how the existing citation and cropping requirements change.

## Goals / Non-Goals

**Goals:**

- Recover figures ADI misses, with a real bounding polygon rather than a page-level citation.
- Make detection provenance explicit and recovery counts measurable per run.
- Gate the cross-check per page so scanned pages are not mined for spurious full-page figures.
- Keep the change reversible by configuration and keep existing behavior when disabled.

**Non-Goals:**

- Replacing ADI as the primary detector, or second-guessing figures it did detect.
- Building the reserved page-level VLM (`PAGE_UNDERSTANDING_MODEL`) — a page-level summary cites a page, not a box, which is exactly the citation quality this design refuses to give up.
- Recovering sub-figures baked into a scanned raster; that remains an open gap with no non-VLM fix.
- Changing the vision prompt, taxonomy, chunk schema, or embedding model.
- Vector-drawing (non-raster) figure recovery.

## Decisions

- **Enumerate placements in step 1, cross-check in step 4A.** Step 1 already opens the PDF and already owns page classification, and the per-page gating decision is a page property, not a figure property. Step 4A already owns figure records, ADI polygons, qualification, and cropping. Splitting along that seam avoids a third PDF open and avoids duplicating classification logic. The alternative — doing everything in 4A — would push page classification into a step whose contract is figures, and would leave `step1-result.json` still document-level for any future consumer.

- **Extend `PreAnalysisResult` with a per-page list rather than replacing `has_text`.** Keeping the document-level boolean preserves every existing consumer and the `step-result-files` contract, while the per-page entries carry what the gate needs. A breaking replacement would buy nothing here.

- **Gate on image coverage of the page, not on a document-level scanned flag.** A scanned page is one full-page raster with no discrete sub-objects; a deliberate full-bleed photo is structurally identical. Coverage is the signal that actually separates "nothing to mine here" from "a figure sits alongside live text", and applying it per page handles the rare genuinely mixed document (scanned exhibits merged into a digital report) without assuming one classification for the file.

- **Treat a placement as already-detected on substantial overlap with any ADI figure, rather than requiring an exact match.** ADI polygons are layout-derived and rarely coincide exactly with the PDF placement rectangle; requiring exact geometry would duplicate most figures. The threshold is configurable because tolerance depends on document family.

- **Recovered figures re-enter the existing 4B qualification unchanged.** Recovery answers "does a figure exist here", which is a different question from "is it worth indexing". Running recovered figures through the same geometric and textual rules keeps one filtering policy instead of two, and keeps page furniture out of the index regardless of which detector found it.

- **Assign recovered figures figure indices that do not collide with ADI's.** Figure index participates in citations and in the chunk id, so a recovered figure must be addressable without renumbering ADI's figures, whose indices are already referenced by prior runs and by OCR merge logic.

- **Provenance is a field on the figure record, not an inference from shape.** Downstream code and humans both need to know which detector produced a figure in order to measure the gap; deriving it from whether a polygon happens to match a placement would be fragile and unmeasurable.

## Risks / Trade-offs

- [Risk] The cross-check surfaces decorative page furniture ADI deliberately ignored, inflating the index → Mitigation: recovered figures pass through the same 4B rejection rules, and recovery counts are reported per run so a spike is visible.
- [Risk] Overlap threshold too strict duplicates figures; too loose suppresses real recoveries → Mitigation: make it configurable, and validate against the known-good corpus where the expected recovery set is already established.
- [Risk] Coverage-based gating misclassifies a legitimate full-bleed figure page as scanned and skips it → Mitigation: accept it deliberately — the alternative is treating every scanned page as one giant figure, which is the worse failure — and record the skip so it is diagnosable.
- [Risk] Placement rectangles are in PyMuPDF points while ADI polygons are in inches → Mitigation: convert at the boundary and cover the conversion with tests; this unit mismatch has already caused bugs in this pipeline.
- [Risk] Reprocessing changes existing chunk ids and index contents → Mitigation: reprocess deliberately per document, and note that content-derived document identity means a re-upload of unchanged bytes is skipped unless the name-index entry is cleared first.

## Migration Plan

1. Land the per-page classification in step 1 first; it is additive and safe to deploy alone.
2. Land the cross-check and provenance in step 4A behind a configuration flag, defaulted off.
3. Enable on the known corpus, confirm pages 6 and 8 of `162000-159772.pdf` are recovered and that previously detected figures are unchanged and not duplicated.
4. Reprocess the existing test documents, clearing their name-index entries so identical bytes are not skipped.
5. Roll back by disabling the flag; reader-detected behavior is unchanged and no artifact schema is removed.

## Open Questions

- Whether the overlap threshold needs different defaults per document family, or whether one default holds across the corpus. This is a tuning value behind a configurable setting and does not change the contract, the approach, or the task breakdown.
