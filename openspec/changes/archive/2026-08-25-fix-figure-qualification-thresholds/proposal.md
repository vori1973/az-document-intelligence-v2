## Why

Deterministic qualification (4B) is rejecting real product photographs as noise on catalog-style documents. On a 159-page product catalog (159 pages, 330 detected figures) it rejected 135 figures, and the rejections are dominated by two rules firing far outside their intent:

- **Undersized rule.** `FIGURE_MIN_AREA_RATIO` defaults to `0.01` — a figure must cover 1% of a US Letter page (about 0.94 in²) to survive. 105 figures were rejected as `low_value_graphic`, but only 59 of those are the repeated 0.33in corner logo the rule exists to remove. The other 46 are individual product photographs — small components and fittings — that a parts catalog lists at exactly that size. Spot-checking the largest rejections confirms real instrument imagery, not rules or separators.
- **Aspect-ratio rule.** `FIGURE_MAX_ASPECT_RATIO` defaults to `8.0`. A surgical instrument is a long thin object; photographed against white, its bounding box is legitimately 10:1 or worse. 16 figures were rejected as `decorative_geometry`, and inspection shows full product photographs — an elongated product with its shaft and printed branding — not hairlines.

Both rules were tuned against technical manuals, where a sub-1% region genuinely is a rule or a bullet glyph. They do not survive contact with a product catalog, and the failure is silent and one-directional: a rejected figure is never cropped, never described, and never indexed, so the catalog's actual subject matter is absent from retrieval.

The rules are still needed — the corner logo repeats on 59 pages and would otherwise cost 59 vision calls and pollute the index with 59 identical descriptions. The fix is to make the rule discriminate on repetition rather than on size alone, and to loosen the size and shape thresholds to where they only catch true furniture.

## What Changes

- Add a repetition signal: a figure that is small AND recurs at the same normalized position and size across many pages of the document is page furniture regardless of what it depicts, and SHALL be rejected on that combined evidence. Repetition alone SHALL NOT reject, because a fixed catalog grid places different products in the same slot on every page.
- Lower the default minimum area ratio so a legitimately small product photograph is no longer rejected for its size alone.
- Raise the default maximum aspect ratio so an elongated product photograph is no longer rejected as a separator.
- Keep both thresholds configurable and keep the existing caption/reference override intact.

## Capabilities

### Modified Capabilities
- `figure-understanding`: The deterministic qualification requirement gains repetition across pages as a rejection trigger, and its size and shape triggers are retuned so they no longer reject legitimate small or elongated figures.

## Impact

- `src/activities/step4a_figures.py` — repetition detection, revised threshold defaults.
- `src/models/types.py` — repetition count on `FigureFeatures`.
- `tests/unit/test_figure_qualification.py` — coverage for the repetition rule and the retuned thresholds.
- `figures.json` and `step4a-result.json` contents; rejection reason mix changes.
- Vision call volume rises on catalog-style documents, because figures previously rejected now qualify. Measured across the eight pulled runs (615 figures): rejections fall from 175 to 90, recovering 87 figures, and no figure that qualifies today becomes rejected. Five of the eight documents are unaffected by the repetition rule because nothing in them repeats on 5+ pages.
- Documents already ingested must be reprocessed for the recovered figures to reach the index.
