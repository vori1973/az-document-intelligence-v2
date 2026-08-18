# Design — fix figure qualification thresholds

## Context

4B runs per figure, in a loop over pages, with no document-level view. That is why it can only ask "is this small?" and not "is this the same thing I saw on 58 other pages?". The repetition signal requires a document-wide pass, so the loop structure has to change: collect features for every figure first, tally positions, then qualify.

`normalized_position_group` already exists on `FigureFeatures` and already encodes exactly the right key — `x0:y0:w:h` normalized to page dimensions, rounded to two decimals. It was computed and stored but never used for a decision. The corner logo produces a single group with 59 members; the next-largest non-furniture group has 4. The signal separates cleanly.

## Decisions

**Repetition is counted, not inferred from position.** Rejecting anything in the bottom 5% of the page would also reject a full-bleed photograph that runs to the page edge. Counting recurrences is direct evidence of furniture and does not assume where furniture lives.

**Repetition alone is NOT sufficient — it must be paired with a size ceiling.** This was the first design's mistake, and the corpus disproved it. A catalog with a fixed grid layout puts a *different* product in the *same* slot on every page of a section, so `normalized_position_group` recurrence conflates "the same graphic repeated" with "the same slot in a repeated layout". In the reference document, eight position groups recur on 4 pages each and every one is genuine content — needle-size charts, instrument photographs — not furniture. Rejecting on a bare count of 4 would have destroyed 32 real figures.

PDF object identity was evaluated as the discriminator and rejected. A PDF may share one image XObject across pages, so identical `xref` values would be exact, free proof that the same artwork repeats. Measurement shows the corpus does not work that way: the 59-page corner logo resolves to a single `xref` appearing on **one** page, and the hardware catalog header logo resolves to **15 distinct xrefs**, one per page. Neither known furniture case is deduplicated — each page carries its own private copy. Producers also wrap page furniture in per-page Form XObjects, and `get_image_info(xrefs=True)` reports `xref 0` for images nested inside them, so the placement xref is not stable even when the underlying bytes are shared. Documents do differ in how aggressively they deduplicate — one corpus document has 2790 placements over 1961 distinct xrefs while another has 1175 over 1175 — but that variation is a property of the producing tool, not a signal about the artwork. Object identity may be retained later as an *optional confirming* signal where sharing genuinely exists, since it is free once placements are enumerated, but it cannot be the detector: on this corpus it catches zero of the two known furniture cases.

Pixel comparison was evaluated as the discriminator and rejected. ADI's polygon for the same logo jitters by a few hundredths of an inch between pages, so crops of identical artwork differ: exact hashing of the 59-instance corner logo yields 45 distinct hashes, and a 16×16 perceptual hash spreads it over a Hamming distance of 45. Meanwhile some genuine content repeats byte-identically across a 4-page section. Content hashing separates the two classes worse than geometry does, at much higher cost.

What does separate them cleanly is size combined with recurrence:

| group | pages | % of doc | area | truth |
|---|---|---|---|---|
| product catalog corner logo | 59 | 37% | 0.0011 | furniture |
| MS Surface logo | 15 | 79% | 0.0031 | furniture |
| product catalog footer bar | 14 | 9% | 0.0080 | furniture |
| product catalog content groups (×8) | 4 | 3% | 0.0134–0.0477 | content |

Every furniture group is under 1% of the page; every repeating content group is above 1.3%. The 1% figure is the *old* `MIN_AREA_RATIO`. It was a correct measure of "small enough to be suspicious" and a wrong measure of "small enough to delete on sight" — so it is retained as a furniture-eligibility ceiling rather than dropped.

**Threshold: 5 or more distinct pages, and area below 1%.** Observed content groups top out at 4 pages, observed furniture starts at 14, so 5 sits between them with wide margins on both sides — and the area ceiling, not the count, is the real safety net. Configurable via `FIGURE_REPEAT_PAGE_THRESHOLD` and `FIGURE_FURNITURE_AREA_CEILING`.

Repetition counts *distinct pages*, not figure instances: two copies of the same graphic on one page is a layout, not furniture.

**Minimum area ratio 0.01 → 0.002.** Measured against the corpus: at 0.002 every one of the 59 logo instances still falls below the line and zero real photographs do. At 0.003 three real photographs are lost. The rule keeps its purpose — it still removes true hairlines and glyph-sized regions — and now the repetition rule carries the furniture case that size was being misused to cover.

**Maximum aspect ratio 8.0 → 12.0.** The rejected instrument photographs measure 10.3:1 to 13.4:1; true separator rules in this corpus measure far higher or have negligible area. 12.0 with the added area guard below keeps separators rejected while admitting the instruments. Genuine hairlines are caught by the area rule regardless, since a rule's height is a fraction of a point.

**Aspect-ratio rejection gains an area guard.** A shape trigger alone cannot distinguish a long photograph from a long line. Requiring the figure to also be small before rejecting it for shape means a large elongated region — which has enough pixels to be a photograph — is never dropped on shape alone. This is the same conservatism the module already states: a false rejection silently removes content, a false positive costs one vision call.

## Measured impact across the corpus

Simulating the proposed rules over all eight pulled runs (615 figures):

| document | figures | rejected now | rejected after | recovered |
|---|---|---|---|---|
| product catalog | 330 | 135 | 73 | 62 |
| hardware catalog | 57 | 21 | 15 | 6 |
| technique guide | 189 | 10 | 10 | 0 |
| hardware factsheet | 11 | 7 | 0 | 7 |
| clinical study | 12 | 1 | 0 | 1 |
| patient brochure | 5 | 1 | 0 | 1 |
| clinical reference | 9 | 0 | 0 | 0 |
| single-page datasheet | 2 | 0 | 0 | 0 |
| **total** | **615** | **175** | **90** | **87** |

No figure that is a candidate today becomes rejected under the new rules. The change is purely recall-positive: 87 figures recovered, and the two documents that carry a repeated logo still reject it — the product catalog's corner logo by size, the hardware catalog's header logo by repetition.

Documents with few figures are unaffected or improve; none regress. The rule is inert on the five small documents because nothing in them repeats on 5+ pages.

## Rejection reasons

`repeated_furniture` is added as a distinct reason rather than folding into `structural_noise`. The reasons are the diagnostic surface in `step4a-result.json` and the annotated PDF; collapsing them would hide whether the corner logo was caught by the rule written for it.

## Risks

Vision call volume rises on catalog documents — roughly 46 additional figures on the reference document, offset by the 59 logo instances now rejected by one rule instead of surviving as 59 individually-qualified candidates under a looser size threshold. Net volume on that document is close to flat. `FIGURE_MAX_VISION_CALLS` still bounds the worst case.

The two-pass restructure holds all figure features in memory before qualifying. That is bounded by figure count per document, which is already bounded by ADI's own per-document limits, and the records are small.
