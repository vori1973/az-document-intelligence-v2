## Purpose

Makes the figures in a document retrievable by what they visually show, not only by the caption printed beneath them, while keeping every citation traceable to the exact page and bounding polygon reported by Azure Document Intelligence.

## ADDED Requirements

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
The pipeline SHALL classify each detected figure as a candidate or a rejection using geometric and textual signals alone, before any vision model is invoked. A figure SHALL only be hard-rejected when a geometric trigger is present AND no textual reference to that figure appears in its caption or in text near it on the page. Rejection thresholds SHALL be configurable.

#### Scenario: Page furniture rejected
- **WHEN** a figure overlaps a header or footer region beyond the configured threshold and no caption or in-text reference points to it
- **THEN** it is rejected and no vision call is made for it

#### Scenario: Referenced figure survives a geometric trigger
- **WHEN** a figure trips a geometric rejection rule but a caption or in-text reference points to it
- **THEN** it is retained as a candidate

#### Scenario: Undersized regions rejected
- **WHEN** a figure occupies less than the configured minimum fraction of the page and is unreferenced
- **THEN** it is rejected as a rule or separator

#### Scenario: Full-page graphics are retained for review
- **WHEN** a figure occupies more than the configured maximum fraction of the page
- **THEN** it is retained as a candidate carrying a routing signal, because a full-page diagram is often the most valuable figure present

#### Scenario: Extreme aspect ratio rejected
- **WHEN** an unreferenced figure's aspect ratio exceeds the configured maximum
- **THEN** it is rejected as a separator or rule

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

#### Scenario: Per-document call volume is bounded
- **WHEN** a document contains more qualified figures than the configured per-document maximum
- **THEN** no more than that maximum number of vision requests are issued

### Requirement: Model output is grounded and never authoritative for citations
The vision description SHALL be treated as retrieval metadata only. Page number, bounding polygon, and figure index in a figure's citation SHALL always originate from Document Intelligence and SHALL NOT be derived from model output. The model SHALL be constrained to describe only what is visible and to declare unreadable content as uncertain rather than inferring it.

#### Scenario: Citation provenance preserved
- **WHEN** a figure chunk is produced for a figure that was described by the vision model
- **THEN** its page, bounding polygon, and figure index match the values Document Intelligence reported for that figure

#### Scenario: Unreadable content declared
- **WHEN** text within a figure is not legible in the crop
- **THEN** the stored description declares the uncertainty rather than asserting a value

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
