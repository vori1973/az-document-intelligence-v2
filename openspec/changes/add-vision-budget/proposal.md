## Why

Figure understanding (4C) stops after the first 60 qualified figures. The limit is a bare slice over a page-ordered list, so it does not sample the document — it truncates it. Every figure past the cut is invisible to retrieval, and because the list is ordered by page, the invisible region is always the *back* of the document.

Measured across the eight pulled runs, 440 figures qualify and **254 of them (58%) are never analyzed**. Two documents carry the entire loss:

| document | pages | qualified | analyzed | lost |
|---|---|---|---|---|
| product catalog | 159 | 195 | 60 | 135 |
| technique guide | 72 | 179 | 60 | 119 |

On the technique guide the cut lands in the middle of page 22, so pages 1–21 are richly described and pages 22–72 contain nothing. A reader cannot tell the difference between "this document has no figures after page 22" and "we stopped looking", and neither can the index.

Three separate defects follow from this:

- **Truncation is silent.** Nothing in `step4c-result.json` records that the budget bound, so a run that analyzed 34% of its figures reports success identically to one that analyzed all of them.
- **Truncated figures are still indexed, uselessly.** 102 of the technique guide's 177 figure chunks carry `text_for_embedding` of exactly `"[Figure]  (Page 22)"` — no description, no caption, no component terms. They cannot be retrieved by any query about what they show, and they dilute the index with near-duplicate low-information vectors. This also contradicts the existing requirement that qualification, not the vision budget, governs index contents.
- **The cap masks the qualification work.** `fix-figure-qualification-thresholds` recovers 87 figures. With a 60 cap, product catalog goes from 195 qualified to 257 qualified and still analyzes exactly 60 — the change would produce byte-identical output and be unverifiable.

A fixed cap is the wrong shape for the problem. Figure density is a property of the document, not a constant: observed density ranges 0.64–2.49 qualified figures per page. A single number is simultaneously too small for a catalog and larger than a three-page factsheet will ever need.

## What Changes

- Replace the fixed figure cap with a budget derived from document length, bounded by an absolute ceiling that exists to stop runaway cost on pathological input rather than to shape normal documents.
- Spend the budget evenly across pages rather than consuming it in page order, so that a document which does exceed its budget degrades to uniform lower-density coverage instead of a fully-described first half and an empty second half.
- Stop indexing figure chunks that have neither a description nor a caption, so an unanalyzed figure leaves no unretrievable placeholder in the index.
- Record whether the budget bound in the step result, so truncation is observable rather than silent.
- Allow the vision model to be selected per document so that small documents, where each figure is a large share of retrievability, can use a more capable model than large ones.

## Capabilities

### Modified Capabilities
- `figure-understanding`: The vision budget becomes document-derived rather than fixed, is spent evenly across pages, is reported when it binds, and no longer produces index entries for figures it did not analyze.

## Impact

- `src/activities/step4c_understanding.py` — budget computation, page-balanced selection, model selection, telemetry.
- `src/activities/step5_chunks.py` — suppress chunks with neither description nor caption.
- `src/models/types.py` — budget and truncation fields on the 4C result.
- `tests/unit/` — budget derivation, even spend, placeholder suppression.
- **Cost rises.** Measured from 440 real crops (median 2 image tiles, mean 426 base image tokens), analyzing every qualified figure in the corpus costs about $1.22 with `gpt-4o-mini` against roughly $0.55 for the capped behavior today. Per document the worst case is the product catalog at about $0.45.
- Index contents change: unanalyzed figures stop producing chunks, so figure chunk counts fall on truncated documents even as described-figure counts rise.
- Documents already ingested must be reprocessed to gain the figures the old cap excluded.
- Ordering: this change should land **before** `fix-figure-qualification-thresholds`, whose effect is otherwise entirely absorbed by the cap.
