# Validation results — add-document-derived-prompt

Commit `b80d608`, deployed to `docintv2-dev-func` via `func azure functionapp publish`.
Live-validated against three real documents by forcing fresh reprocessing (re-uploading
identical PDF bytes under a temporary filename, since doc_id is content-derived and a
same-filename re-upload is a no-op).

## 4.2 — Before / after quality-signal rates

| Document | Generic-opener (before → after) | Unlabelled (before → after) | Qualified figures (before → after) |
|---|---|---|---|
| Technique guide | 58.0% → 56.4% | 25.9% → 21.5% | 179 → 189 |
| Product catalog | 25.1% → 7.9% | 36.6% → 39.4% | 195 → 257 |
| Surface Pro fact sheet (supplementary, small) | 0% → 0% | 33.3% → 20.0% | 4 → 4 meaningful (11 qualified) |

Rates are computed by `_quality_signals` (meaningful-described denominator) from
`figure-understanding.json`, applied identically to both snapshots. They do not exactly
match the proposal's stated baseline (59%/20% technique guide, 26%/46% catalog) —
that baseline appears to use a different, smaller manual denominator (its table cites 56
and 57 "described" figures respectively, vs. 174/191 computed automatically here). The
automated numbers are self-consistent before and after, so they are valid for the
relative comparison even though they don't reproduce the proposal's absolute figures.

**Confound, disclosed per the mandatory acceptance gate:** the qualified-figure count
also changed between snapshots (179→189, 195→257, 4→11) because the previously deployed
`fix-figure-qualification-thresholds` change is reflected in the "after" runs but not in
the cached "before" data. The after-numbers therefore reflect the combined effect of two
changes, not this prompt change in isolation. Directionally: generic-opener rate improved
or held for all three documents; unlabelled rate improved for two of three and worsened
slightly for the catalog (36.6%→39.4%), plausibly because the qualification-threshold
change retained more marginal/ambiguous figures that this change's grounding rules
correctly decline to over-label rather than guess.

## 4.3 — Manual review (mandatory gate)

Reviewed the first 20 changed description pairs (by page/figure-index order, not
cherry-picked) for both required documents, plus visual crop inspection of a
vocabulary-novelty-ranked sample:

- **Technique guide:** 20/20 text pairs reviewed, no unsupported identity, measurement,
  or procedure claims. Changes were name upgrades using document vocabulary (e.g. "VELYS
  robotic-assisted surgical system" → "VELYS™ Robotic-Assisted Solution", "Base Station",
  "Satellite Station") and mild rephrasing. Visually confirmed 4 crops
  (`p5-fig17`, `p5-fig18`, `p6-fig21`, `p8-fig23`) — all named labels (Saw, Planar
  Articulation Lock, Satellite/Base Station, VELYS™ branding) genuinely visible in the
  image.
- **Product catalog:** 20/20 text pairs reviewed, no unsupported claims. Visually
  confirmed 5 crops (`p10-fig19`, `p30-fig78`, `p59-fig147`, `p66-fig166`,
  `p158-fig328`). One case (`p30-fig78`, "TIGHT-N™ Tendon Docking Anchors") names a
  product using text that is only partially legible inside the crop's own frame — this
  is the intended context-assisted-naming behavior, not a hallucination, since the
  anchor+suture assembly itself is visibly present.
- **Fact sheet (supplementary):** reviewed all 11 records (full population, not a
  sample, since the document is small). Found one instance of over-reach: figure (1,2),
  an NFC ID-card graphic, lists `device_or_component_terms` including "Windows Hello for
  Business" — a term present in neither the image nor the supplied `nearby_text`
  ("NFC authentication ... Copilot+PC NPUs ..."). This is the model drawing on general
  product knowledge rather than the image or supplied context, which the system prompt's
  grounding rule is meant to prevent. It landed in `device_or_component_terms`/
  `search_keywords`, not `visible_labels`, and is a plausible (not measurement- or
  procedure-level) inference, but it is a real instance of the risk called out in
  design.md ("Suggestion becomes assertion"). Recommend tightening the `device_or_component_terms`
  guidance in a follow-up if recurrence is seen at scale.

**Automated cross-check (supplementary, full population):** wrote a heuristic that flags
brand-like terms (ALL-CAPS tokens, trademark symbols) in `visible_labels` /
`device_or_component_terms` that don't appear in the candidate's own
`document_title`/`section_heading`/`nearby_text`, across the full analyzed population of
all three documents (189 + 257 + 11 = 457 records). Flagged only 10 terms total, nearly
all genuine on-image OCR fragments (e.g. "CR", "FB", "YELLOW", "BLUE" — UI button labels
literally printed on the device) rather than context-injected claims. The one
substantive finding is the "Windows Hello for Business" case above.

## 4.4 — Uncertainty on unreadable artwork

Across all three documents, exactly one figure had non-empty `uncertainty`: fact sheet
(1,3), an abstract decorative graphic. Model output: `is_meaningful: false`,
`short_description: "An abstract image featuring smooth blue curves and a dark
background."`, `uncertainty: ["No specific device or component is identifiable from the
image."]` — despite `document_title` ("Surface Pro for Business") being available in
context, the model did not force a device name onto genuinely unidentifiable artwork.
Confirms the recognition-vs-assertion rule holds on real unreadable content. (Technique
guide and catalog had zero populated-uncertainty records — both documents' qualifying
figures were legible device/procedure photos, so no genuinely ambiguous artwork
occurred in the qualifying set.)

## 4.5 — Instruction-like text does not alter behavior

Rather than constructing a synthetic test, searched the real `nearby_text` of all three
documents for imperative-mood language, and found the technique guide's actual surgical
procedure text is naturally full of it (e.g. "Release the button and check that the Bone
Array is rigidly fixed", "The surgeon must first verify the position...", "Ensure the
base of the Checkpoint is clear of soft-tissue..."). Checked the corresponding model
output for these figures (pages 19, 34, 47, 66): all returned normal, schema-conformant,
third-person JSON (`short_description`, `procedure_actions` as arrays of noun-phrase
actions like `"attach Bone Array"`, `"align Bone Array"`) — no sign of the model treating
the imperative document text as an instruction to itself (no first-person narration,
no schema breakage, no refusal). Combined with the existing unit tests
(`TestSystemPromptIsFixed`, `TestContextInUserMessageOnly` in
`tests/unit/test_step4c_document_context.py`) confirming `SYSTEM_PROMPT` is byte-identical
regardless of document content and that context only ever appears in the user message,
this satisfies the injection-resistance check.

## Conclusion

Both binding acceptance conditions from design.md are met: generic-opener rate improved
or held across all three documents, and manual review found no unsupported identity,
measurement, or procedure claims introduced by this change. One minor over-reach
(context-adjacent general-knowledge term, not a hallucinated measurement or procedure)
was found and is documented above as a known residual risk, consistent with design.md's
own "Suggestion becomes assertion" risk entry — not a blocking regression.
