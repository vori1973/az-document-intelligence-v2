# Tasks — fix figure qualification thresholds

## 1. Feature model
- [ ] 1.1 Add `repeat_page_count` to `FigureFeatures` in `src/models/types.py`, defaulting to 1 so existing artifacts still validate.

## 2. Qualification
- [ ] 2.1 Add `FIGURE_REPEAT_PAGE_THRESHOLD` (default 3) alongside the existing thresholds in `step4a_figures.py`.
- [ ] 2.2 Lower `FIGURE_MIN_AREA_RATIO` default to 0.002 and raise `FIGURE_MAX_ASPECT_RATIO` default to 12.0.
- [ ] 2.3 Restructure the main loop into two passes: build every candidate's features first, tally distinct pages per `normalized_position_group`, then qualify.
- [ ] 2.4 Add the `repeated_furniture` rejection to `_qualify`, gated on the reference override like every other hard rejection.
- [ ] 2.5 Gate the aspect-ratio rejection on the figure also being small, so a large elongated photograph is not rejected on shape alone.

## 3. Tests
- [ ] 3.1 Repeated figure above the threshold is rejected as `repeated_furniture`.
- [ ] 3.2 Repeated figure with a caption or in-text reference is retained.
- [ ] 3.3 Figure at the repetition threshold is retained (boundary).
- [ ] 3.4 Small non-repeating figure above the new minimum area is retained.
- [ ] 3.5 Elongated figure within the new aspect maximum is retained; a thin low-area rule is still rejected.
- [ ] 3.6 Run the unit suite.

## 4. Verify against the corpus
- [ ] 4.1 Re-qualify the 159-page product catalog's figures with the new rules and confirm all 59 logo instances are rejected as `repeated_furniture` and the product photographs qualify.
