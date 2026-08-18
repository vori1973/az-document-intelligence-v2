## MODIFIED Requirements

### Requirement: Vision analysis is grounded in the document it came from
The pipeline SHALL supply document-derived context to the vision model alongside each figure crop. The context SHALL include the document title, the section or heading the figure appears under when one is available, and text appearing near the figure on its page. Context length SHALL be bounded.

Document-derived context SHALL be supplied as data accompanying the figure, and SHALL NOT alter the instructions that constrain the model. The rules forbidding invented device identity, procedure sequence, clinical recommendation, measurements, settings, and unsupported component names SHALL remain fixed and identical for every document.

Supplied context SHALL be usable only as candidate vocabulary for naming what is visibly present in the figure. It SHALL NOT be treated as evidence that anything is present. Where the figure does not visibly support a term available in the context, the pipeline SHALL record the limitation in the uncertainty field rather than asserting the term.

#### Scenario: Unlabelled figure named from document vocabulary
- **WHEN** a figure shows a component carrying no legible label, and the document title or nearby text names the product family it belongs to
- **THEN** the description may name the component using that vocabulary, because the context supplies a name for what is visibly present

#### Scenario: Context does not license unsupported claims
- **WHEN** the document context states a measurement, setting, or procedure step that is not visible in the figure
- **THEN** the description does not assert it, and the limitation is recorded in the uncertainty field

#### Scenario: Grounding rules are document-independent
- **WHEN** figures from two different documents are analyzed
- **THEN** the instructions constraining invention are identical for both, and only the accompanying context differs

#### Scenario: Untrusted document text cannot redirect the model
- **WHEN** a document contains text resembling instructions to the model
- **THEN** that text is supplied only as document context and the model's constraints are unchanged

#### Scenario: Context is bounded
- **WHEN** the text near a figure is long
- **THEN** the supplied context is truncated to the configured limit so prompt size and cost stay bounded

#### Scenario: Missing context degrades cleanly
- **WHEN** no section heading or nearby text can be determined for a figure
- **THEN** the figure is analyzed with whatever context is available and the run succeeds

### Requirement: Description quality is measurable
The pipeline SHALL report per-document signals of figure description quality, including the proportion of meaningful figures whose description characterizes the medium rather than the subject, and the proportion exposing no visible labels. These signals SHALL be derivable from pipeline output without external ground truth.

#### Scenario: Quality signals reported
- **WHEN** figure understanding completes for a document
- **THEN** the step result records the count of meaningful described figures, the generic-description proportion, and the unlabelled proportion

#### Scenario: Quality regression is detectable
- **WHEN** a document is reprocessed after a prompt or model change
- **THEN** the reported signals can be compared against the previous run to detect a regression
