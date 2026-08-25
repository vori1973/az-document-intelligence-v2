## MODIFIED Requirements

### Requirement: Figure crops are produced for every detected figure
The pipeline SHALL produce a raster crop of every detected figure, bounded by that figure's reported polygon, and SHALL persist each crop as a run artifact addressable by page number and figure index. A figure is detected when Document Intelligence reports it or when the embedded image placement cross-check recovers it, and both SHALL be cropped by the same mechanism. Crop resolution SHALL be configurable and SHALL default to a resolution at which embedded text is legible.

#### Scenario: Crop produced for a detected figure
- **WHEN** Document Intelligence reports a figure on page 3 with a bounding polygon
- **THEN** a raster crop of that polygon region is stored as a run artifact identifying page 3 and that figure's index

#### Scenario: Crop produced for a recovered figure
- **WHEN** a figure on page 6 is recovered by the placement cross-check rather than reported by Document Intelligence
- **THEN** a raster crop of its polygon region is stored as a run artifact identifying page 6 and that figure's index

#### Scenario: Document with no figures
- **WHEN** a document contains no detected figures
- **THEN** no crops are produced and the pipeline continues without error

#### Scenario: Crop failure does not fail the run
- **WHEN** a crop cannot be produced for one figure
- **THEN** that figure is recorded as not croppable and the remaining figures are still processed

### Requirement: Model output is grounded and never authoritative for citations
The vision description SHALL be treated as retrieval metadata only. Page number, bounding polygon, and figure index in a figure's citation SHALL always originate from a deterministic detector — either Document Intelligence or the PDF's own embedded image placement — and SHALL NOT be derived from model output. Each figure SHALL record which detector its citation came from. The model SHALL be constrained to describe only what is visible and to declare unreadable content as uncertain rather than inferring it.

#### Scenario: Citation provenance preserved
- **WHEN** a figure chunk is produced for a figure that was described by the vision model
- **THEN** its page, bounding polygon, and figure index match the values its deterministic detector reported for that figure

#### Scenario: Recovered figure citation comes from the PDF
- **WHEN** a figure chunk is produced for a recovered figure
- **THEN** its bounding polygon corresponds to that figure's embedded image placement rectangle and its record declares recovery provenance

#### Scenario: Unreadable content declared
- **WHEN** text within a figure is not legible in the crop
- **THEN** the stored description declares the uncertainty rather than asserting a value
