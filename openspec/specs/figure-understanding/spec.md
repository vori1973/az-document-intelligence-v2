## Purpose

Makes the figures in a document retrievable by what they visually show, not only by the caption printed beneath them, while keeping every citation traceable to the exact page and bounding polygon reported by Azure Document Intelligence.

## Requirements

### Requirement: Figure crops are produced for every detected figure
The pipeline SHALL produce a raster crop of every figure that Document Intelligence detects, bounded by that figure's reported polygon, and SHALL persist each crop as a run artifact addressable by page number and figure index. Crop resolution SHALL be configurable and SHALL default to a resolution at which embedded text is legible.

#### Scenario: Crop produced for a detected figure
- **WHEN** Document Intelligence reports a figure on page 3 with a bounding polygon
- **THEN** a raster crop of that polygon region is stored as a run artifact identifying page 3 and that figure's index

#### Scenario: Document with no figures
- **WHEN** a document contains no detected figures
- **THEN** no crops are produced and the pipeline continues without error

#### Scenario: Crop failure does not fail the run
- **WHEN** a crop cannot be produced for one figure
- **THEN** that figure is recorded as not croppable and the remaining figures are still processed

### Requirement: Deterministic qualification precedes any model call
The pipeline SHALL classify each detected figure as a candidate or a rejection using geometric, repetition, and textual signals alone, before any vision model is invoked. A figure SHALL only be hard-rejected when a rejection trigger is present AND no textual reference to that figure appears in its caption or in text near it on the page. Rejection thresholds SHALL be configurable.

Rejection triggers SHALL discriminate page furniture from content by evidence that furniture actually exhibits, not by size or shape alone. A figure that is below a configured furniture size ceiling AND recurs at the same relative position and size across more than a configured number of distinct pages SHALL be treated as furniture. Recurrence alone SHALL NOT reject a figure, because a repeated page layout places distinct content in the same position on every page. Size and shape triggers SHALL be set so that a legitimately small or legitimately elongated figure — a product photograph of a small or long object — is not rejected merely for its dimensions.

#### Scenario: Page furniture rejected
- **WHEN** a figure overlaps a header or footer region beyond the configured threshold and no caption or in-text reference points to it
- **THEN** it is rejected and no vision call is made for it

#### Scenario: Small repeated figure rejected as furniture
- **WHEN** an unreferenced figure is below the furniture size ceiling and occupies the same relative position and size on more distinct pages than the configured repetition threshold
- **THEN** it is rejected as furniture and no vision call is made for any of its repeats

#### Scenario: Repeated layout slot holding real content is retained
- **WHEN** a figure recurs at the same position across many pages but is above the furniture size ceiling
- **THEN** it is retained as a candidate, because a repeated grid layout places a different product in that slot on each page

#### Scenario: Repeated figure that is referenced survives
- **WHEN** a figure recurs across many pages but a caption or in-text reference points to it
- **THEN** it is retained as a candidate

#### Scenario: Referenced figure survives a geometric trigger
- **WHEN** a figure trips a geometric rejection rule but a caption or in-text reference points to it
- **THEN** it is retained as a candidate

#### Scenario: Undersized regions rejected
- **WHEN** a figure occupies less than the configured minimum fraction of the page and is unreferenced
- **THEN** it is rejected as a rule or separator

#### Scenario: Small non-repeating figure is retained
- **WHEN** an unreferenced figure is small but occupies at least the configured minimum fraction of the page and does not recur across pages
- **THEN** it is retained as a candidate, because a catalog lists individual products at that size

#### Scenario: Full-page graphics are retained for review
- **WHEN** a figure occupies more than the configured maximum fraction of the page
- **THEN** it is retained as a candidate carrying a routing signal, because a full-page diagram is often the most valuable figure present

#### Scenario: Extreme aspect ratio rejected
- **WHEN** an unreferenced figure's aspect ratio exceeds the configured maximum
- **THEN** it is rejected as a separator or rule

#### Scenario: Elongated product photograph is retained
- **WHEN** an unreferenced figure is elongated but its aspect ratio is within the configured maximum and its area is not negligible
- **THEN** it is retained as a candidate, because a photograph of a long instrument is legitimately elongated

#### Scenario: Rejected figures are not indexed
- **WHEN** a figure is rejected by deterministic qualification
- **THEN** no chunk for it is indexed, so qualification governs index contents and not merely the vision budget

### Requirement: Qualified figures receive one schema-enforced vision call
Each qualified candidate SHALL be described by exactly one vision model request whose response conforms to a fixed schema. The response SHALL classify the figure into a controlled taxonomy and SHALL include a one-sentence description, visible labels, component terms, warnings, search keywords, a categorical confidence label, and declared uncertainty. A response that does not conform to the schema SHALL be discarded.

#### Scenario: Qualified figure is described
- **WHEN** a qualified figure crop is submitted for understanding
- **THEN** a schema-conforming description with a taxonomy category and a categorical confidence label is stored for that figure

#### Scenario: No qualified figures means no vision calls
- **WHEN** deterministic qualification rejects every figure in a document
- **THEN** no vision request is issued for that document

#### Scenario: Understanding failure degrades gracefully
- **WHEN** the vision request fails after retries for one figure
- **THEN** that figure is retained without a description and the pipeline continues

### Requirement: Vision analysis operates within a document-derived budget
The pipeline SHALL bound the number of figures sent to the vision model per document. The bound SHALL be derived from the document's page count and SHALL be subject to a configured absolute ceiling. Both the per-page allowance and the ceiling SHALL be configurable.

When the number of qualified figures exceeds the budget, the pipeline SHALL distribute the budget across pages rather than consuming it in page order, so that every page containing qualified figures is represented in the analyzed set before any page contributes a second figure. Within a page, larger figures SHALL be preferred.

The pipeline SHALL report the qualified count, the budget, the analyzed count, and whether the budget bound, so that truncation is distinguishable from a document that contains few figures.

#### Scenario: Budget accommodates a normal document
- **WHEN** a document's qualified figure count is within its derived budget
- **THEN** every qualified figure is analyzed and the result reports that the budget did not bind

#### Scenario: Budget scales with document length
- **WHEN** two documents qualify the same number of figures but one has many more pages
- **THEN** the longer document is granted the larger budget

#### Scenario: Absolute ceiling bounds pathological input
- **WHEN** a document is long enough that its page-derived budget exceeds the configured ceiling
- **THEN** the budget is the ceiling, so cost per document remains bounded

#### Scenario: Exceeding the budget degrades evenly across pages
- **WHEN** a document qualifies more figures than its budget allows
- **THEN** figures are selected so that each page with qualified figures contributes before any page contributes an additional figure, and no contiguous range of pages is left wholly unanalyzed

#### Scenario: Truncation is reported
- **WHEN** the budget binds and some qualified figures are not analyzed
- **THEN** the step result records the qualified count, the budget, the analyzed count, and that the budget bound

#### Scenario: Unanalyzed figures are not indexed as placeholders
- **WHEN** a qualified figure is not analyzed because the budget bound, and it has no caption
- **THEN** no chunk is indexed for it, because a chunk carrying neither a description nor a caption cannot be retrieved by what it shows

#### Scenario: Unanalyzed figure with a caption still indexes on its caption
- **WHEN** a qualified figure is not analyzed because the budget bound, but it has a caption
- **THEN** a chunk is indexed using the caption-based text, matching the documented behavior when figure understanding is unavailable

### Requirement: Vision model is selectable per document
The pipeline SHALL allow the vision model to be selected according to the number of figures a document presents, so that documents with few figures may use a more capable model than documents with many. The models and the figure count separating them SHALL be configurable, and configuring a single model for both SHALL be supported.

#### Scenario: Small document uses the higher-accuracy model
- **WHEN** a document's analyzed figure count is at or below the configured premium threshold
- **THEN** figures are analyzed with the configured premium model

#### Scenario: Large document uses the economical model
- **WHEN** a document's analyzed figure count exceeds the configured premium threshold
- **THEN** figures are analyzed with the configured economical model

#### Scenario: Tiering can be disabled
- **WHEN** both tiers are configured to the same model
- **THEN** every document is analyzed with that model and no tiering behavior is observable

### Requirement: Model output is grounded and never authoritative for citations
The vision description SHALL be treated as retrieval metadata only. Page number, bounding polygon, and figure index in a figure's citation SHALL always originate from Document Intelligence and SHALL NOT be derived from model output. The model SHALL be constrained to describe only what is visible and to declare unreadable content as uncertain rather than inferring it.

#### Scenario: Citation provenance preserved
- **WHEN** a figure chunk is produced for a figure that was described by the vision model
- **THEN** its page, bounding polygon, and figure index match the values Document Intelligence reported for that figure

#### Scenario: Unreadable content declared
- **WHEN** text within a figure is not legible in the crop
- **THEN** the stored description declares the uncertainty rather than asserting a value

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

### Requirement: Figure chunks are retrievable by visual content
A figure chunk's embedded text SHALL incorporate the figure's description, visible labels, component terms, warnings, and search keywords when an understanding result is available, so the figure can be retrieved by describing what it shows. The chunk SHALL reference the stored crop so a result can display the image.

#### Scenario: Figure retrievable without a useful caption
- **WHEN** a figure has a generic or missing caption but its description names a visible component
- **THEN** a search for that component term matches the figure chunk

#### Scenario: Chunk carries its image reference
- **WHEN** a figure chunk is indexed and a crop exists for it
- **THEN** the chunk references that crop artifact

#### Scenario: Confidently meaningless figures are not indexed
- **WHEN** the vision result confidently reports a figure as not meaningful
- **THEN** no figure chunk is indexed for it

#### Scenario: Uncertain figures are retained
- **WHEN** the vision result reports a figure as not meaningful with less than high confidence
- **THEN** the figure chunk is still indexed

### Requirement: Figure understanding is optional and backward compatible
Figure understanding SHALL be controllable by configuration. When it is disabled or its results are unavailable, figure chunks SHALL still be produced using the caption-based text that existed before this capability, and the pipeline SHALL complete successfully.

#### Scenario: Understanding disabled
- **WHEN** figure understanding is disabled by configuration
- **THEN** the pipeline completes and figure chunks contain caption-based text

#### Scenario: Understanding results missing
- **WHEN** no understanding results exist for a run
- **THEN** figure chunks are still produced from captions and the run succeeds
