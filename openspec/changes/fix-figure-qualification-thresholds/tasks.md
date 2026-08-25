# Tasks — fix figure qualification thresholds

## 1. Feature model
- [x] 1.1 Add `repeat_page_count` to `FigureFeatures` in `src/models/types.py`, defaulting to 1 so existing artifacts still validate.

## 2. Qualification
- [x] 2.1 Add `FIGURE_REPEAT_PAGE_THRESHOLD` (default 4) alongside the existing thresholds in `step4a_figures.py`.
- [x] 2.2 Lower `FIGURE_MIN_AREA_RATIO` default to 0.002 and raise `FIGURE_MAX_ASPECT_RATIO` default to 12.0.
- [x] 2.3 Add `FIGURE_FURNITURE_AREA_CEILING` (default 0.01) for the maximum size eligible for repeated-furniture rejection.
- [x] 2.4 Restructure the main loop into two passes: build every candidate's features first, tally distinct pages per `normalized_position_group`, then qualify.
- [x] 2.5 Add the `repeated_furniture` rejection to `_qualify`, gated on the reference override like every other hard rejection.
- [x] 2.6 Gate the aspect-ratio rejection on the figure also being small, so a large elongated photograph is not rejected on shape alone.

## 3. Tests
- [x] 3.1 Repeated figure above the threshold is rejected as `repeated_furniture`.
- [x] 3.2 Repeated figure with a caption or in-text reference is retained.
- [x] 3.3 Figure at the repetition threshold is retained (boundary).
- [x] 3.4 Small non-repeating figure above the new minimum area is retained.
- [x] 3.5 Elongated figure within the new aspect maximum is retained; a thin low-area rule is still rejected.
- [x] 3.6 Run the unit suite.

## 4. Verify against the corpus
- [x] 4.1 Re-qualify the 159-page product catalog's figures with the new rules and confirm all 59 logo instances are rejected as `repeated_furniture` and the product photographs qualify.
