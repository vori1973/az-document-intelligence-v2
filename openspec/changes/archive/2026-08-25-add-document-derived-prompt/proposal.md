## Why

The 4C system prompt is a fixed string that opens `"You classify and describe figures extracted from technical and medical documents"`. Every figure in every document is described against that same sentence, with per-figure context limited to page number, ADI caption, and routing signals. The model is told the *genre* of the corpus and nothing about the *document* the figure came from.

The cost is measurable. Across 162 meaningful described figures in the eight pulled runs:

| document | described | generic opener | no visible labels |
|---|---|---|---|
| technique guide | 56 | 33 (59%) | 11 (20%) |
| product catalog | 57 | 15 (26%) | 26 (46%) |
| hardware catalog | 25 | 4 (16%) | 1 (4%) |
| clinical reference | 6 | 2 (33%) | 0 |
| clinical study | 11 | 1 (9%) | 0 |
| **total** | **162** | **57 (35%)** | **40 (25%)** |

A "generic opener" is a description beginning *"An illustration showing…"*, *"A diagram of…"* — text that describes the figure's medium rather than its subject. Such a description is nearly worthless for retrieval: it embeds close to every other figure in the document and matches no query a reader would type.

The failure is concentrated where the artwork carries no readable text. On the product catalog 46% of described figures expose no visible labels at all, and those are exactly the cases where the model has nothing to name the subject with. It correctly declines to guess — which is the behavior the grounding rules demand — but it then has nothing left to say, and falls back to describing the medium.

That is a *context* deficiency, not a capability one. The same generic model, when a label is legible, extracts precise and correct terminology: across the technique guide run it produced 75 distinct correct product terms naming specific implant lines, tracker arrays, and instrument components. The vocabulary is reachable. The model simply is not told that it is looking at a robotic-assisted knee surgical technique guide for a specific device family, so when the artwork is unlabelled it cannot connect an unlabelled tracker array to the device family named on every page of the document it came from.

The document already contains this context. The title, the section heading above the figure, and the body text near it are all extracted by earlier steps and discarded before the vision call.

## What Changes

- Supply document-level context — at minimum the document title, and the section or heading the figure sits under — to the vision model alongside the figure crop.
- Supply text near the figure on its page, which the qualification step already locates in order to detect in-text references.
- Keep every grounding and anti-invention rule fixed in the prompt, not derived from the document. Context SHALL widen what the model may recognize, never what it may assume.
- Require that supplied context is treated as candidate vocabulary for naming what is visible, and explicitly not as license to assert anything not visible in the image.
- Report the description-quality signals — generic-opener rate and unlabelled rate — so the change is verifiable and regressions are detectable.

## Capabilities

### Modified Capabilities
- `figure-understanding`: The vision call receives document-derived context in addition to the figure crop, while the grounding rules that constrain it remain fixed and document-independent.

## Impact

- `src/activities/step4c_understanding.py` — prompt assembly, context plumbing.
- `src/activities/step4a_figures.py` — carry nearby text and section heading onto the candidate rather than discarding them after reference detection.
- `src/models/types.py` — context fields on `FigureCandidate`.
- `tests/unit/` — context assembly, truncation, and grounding-rule invariance.
- Prompt token cost rises modestly; context is text-only and small beside image tiles, which dominate at a mean 426 tokens per figure.
- Description text changes for already-ingested documents only on reprocessing.
- **Risk requiring explicit guarding:** supplying document vocabulary raises the chance the model applies a plausible term to artwork that does not show it. For a regulated medical device manufacturer a confidently wrong component name is worse than a vague description. The grounding rules and the `uncertainty` field are the mitigation and SHALL NOT be weakened by this change; acceptance requires that invented-identity behavior does not increase.
