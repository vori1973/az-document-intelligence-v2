## Context

`SYSTEM_PROMPT` in `step4c_understanding.py` is a module-level constant naming the corpus genre — "technical and medical documents". `_build_user_content` adds page number, ADI caption, and routing signals. Nothing identifies the document.

Baseline quality across 162 meaningful described figures: 35% generic openers, 25% with no visible labels. The two rates correlate — where artwork carries no legible text the model has no vocabulary to name the subject and describes the medium instead.

## Goals / Non-Goals

**Goals.** Give the model the document's own vocabulary so it can name unlabelled subjects. Keep grounding fixed. Make description quality measurable.

**Non-Goals.** Changing which figures are analyzed (`add-vision-budget`, `fix-figure-qualification-thresholds`). Changing the response schema. Fine-tuning or domain-specific models — explicitly rejected below.

## Decisions

### Context is injected as user-message data, not into the system prompt

The system prompt stays a fixed constant carrying the grounding rules. Document context arrives in the user message next to the crop, labelled as document context.

Keeping the two separate preserves a single reviewable statement of what the model may never do. If document text were concatenated into the system prompt, a document containing instruction-like phrasing could restate the model's role, and the anti-invention rules would become document-dependent — the one property they must not have. This is a prompt-injection boundary as much as a design preference: ingested PDFs are untrusted input.

### Context set: title, section heading, nearby page text

- **Document title** — the vocabulary anchor. "<product family> Robotic-Assisted Solution" tells the model the device family for every unlabelled tracker array in the document.
- **Section heading** — narrows to the procedure stage, distinguishing a femoral from a tibial array in otherwise similar artwork.
- **Nearby page text** — already located by 4A for in-text reference detection and currently discarded. It is the strongest signal for unlabelled artwork, since the sentence beside a figure usually names it.

Nearby text is bounded to a small character budget and truncated at a word boundary, so a text-dense page cannot dominate the prompt or the cost.

### Context widens recognition, never assertion

The prompt SHALL state that supplied context is candidate vocabulary for naming what is visibly present, and is not evidence that anything is present. The distinction is the entire safety argument:

- Permitted: artwork shows an unlabelled tracker array; the document is a robotic-assisted surgical technique guide; the model names it as a <product family> tracker array.
- Forbidden: the document mentions a 30°–50° pin angle; the artwork shows a pin at no legible angle; the model states the angle.

The existing `uncertainty` field remains the required outlet, and the existing rule against inventing measurements, settings, and model numbers is unchanged.

### Rejected: a domain-specific or fine-tuned model

The evidence says the deficiency is context, not capability. The generic model already produced 75 distinct correct product terms on the technique guide, and it fails specifically and only where text is illegible — that is, it declines to name what it cannot read. That is the failure mode the spec asks for.

A domain-tuned model would have the opposite failure mode: confident, fluent, invented clinical specificity on exactly the unlabelled artwork where the generic model currently abstains. For a regulated device manufacturer whose figures inform surgical technique, a description that is wrong and authoritative is materially worse than one that is vague. Tuning would also need re-validation per device family and would not fix the root cause, since an unlabelled figure with no document context is under-determined for any model.

Reconsider only if context injection lands and the generic-opener rate stays high on figures that *do* have adequate context.

### Quality is measured, not asserted

Emit per-document generic-opener rate and unlabelled rate in the 4C result. These are computable from output text with no ground truth, which is what makes them usable as a standing regression signal rather than a one-off evaluation.

Acceptance: generic-opener rate falls materially on the two documents where it is worst (technique guide 59%, product catalog 26%), and manual review of a sample from each shows no increase in unsupported identity claims. The second condition is the binding one — a drop in generic openers achieved by inventing specifics is a regression, not an improvement, and the rates alone cannot distinguish those cases.

## Risks / Trade-offs

- **Suggestion becomes assertion.** The central risk. Mitigated by the recognition/assertion rule, the unchanged grounding rules, the retained `uncertainty` outlet, and a mandatory sampled manual review before archiving. Automated rates cannot detect this class of regression on their own.
- **Prompt injection from ingested PDFs.** Context is untrusted. Mitigated by confining it to the user message, labelling it as document context, and bounding its length.
- **Token cost.** Small relative to image tiles (mean 426 tokens per figure); bounded by the nearby-text character budget.
- **Context can be wrong.** A mis-detected heading supplies misleading vocabulary. Bounded by the same rule that context never licenses an assertion.

## Migration

Prompt and plumbing only; no state migration. Existing descriptions persist until documents are reprocessed. Baseline rates recorded above serve as the before-measurement.
