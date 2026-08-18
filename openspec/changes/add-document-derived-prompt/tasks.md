## 1. Carry context through the pipeline

- [ ] 1.1 Add `document_title`, `section_heading`, and `nearby_text` to `FigureCandidate` in `src/models/types.py`
- [ ] 1.2 In `src/activities/step4a_figures.py`, retain the nearby-page text already gathered for in-text reference detection instead of discarding it after the reference check
- [ ] 1.3 Determine the section heading for each figure from the ADI layout structure, falling back to none when it cannot be determined
- [ ] 1.4 Source the document title from the ADI result, falling back to the source filename
- [ ] 1.5 Unit test: candidates carry context; missing heading or nearby text does not fail qualification

## 2. Prompt assembly

- [ ] 2.1 Extend `_build_user_content` in `step4c_understanding.py` to include a clearly labelled document-context block alongside the existing page, caption, and routing-signal lines
- [ ] 2.2 Bound `nearby_text` with `FIGURE_CONTEXT_MAX_CHARS` (default `600`), truncating at a word boundary
- [ ] 2.3 Add the recognition-versus-assertion rule to `SYSTEM_PROMPT`: supplied context names what is visible and is never evidence that something is present
- [ ] 2.4 Keep `SYSTEM_PROMPT` a fixed constant — no document text is interpolated into it
- [ ] 2.5 Unit test: context appears in the user message only; the system prompt is byte-identical across two different documents
- [ ] 2.6 Unit test: over-long nearby text is truncated to the configured limit

## 3. Quality signals

- [ ] 3.1 Compute per-document generic-opener rate over meaningful described figures, matching descriptions that open by naming the medium ("An illustration showing…", "A diagram of…")
- [ ] 3.2 Compute per-document unlabelled rate — meaningful described figures with no `visible_labels`
- [ ] 3.3 Add both, with the meaningful-described denominator, to the 4C result model and `step4c-result.json`
- [ ] 3.4 Unit test: both rates computed correctly, including the zero-described-figures case

## 4. Validation

- [ ] 4.1 Run `.venv/bin/python -m pytest tests/ -q`
- [ ] 4.2 Re-run the technique guide and the product catalog; compare against baseline generic-opener rates of 59% and 26% and unlabelled rates of 20% and 46%
- [ ] 4.3 **Manually review a sample of at least 20 changed descriptions per document for unsupported identity, measurement, or procedure claims.** This gate is mandatory — a fall in generic openers achieved by inventing specifics is a regression the automated rates cannot detect
- [ ] 4.4 Confirm figures whose artwork is genuinely unreadable still populate `uncertainty` rather than asserting a context-derived term
- [ ] 4.5 Verify a document containing instruction-like text does not alter model behavior
- [ ] 4.6 Record before and after rates and the manual review outcome in the change folder before archiving
