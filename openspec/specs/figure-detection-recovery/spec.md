## Purpose

Catches figures the document reader fails to detect by cross-checking the PDF's own embedded image placements against the reader's reported figures, so a missed figure is recovered with a real bounding polygon instead of being silently absent from the index.

## Requirements

### Requirement: Embedded image placements are enumerated independently of the document reader
The pipeline SHALL enumerate the PDF's own embedded raster image placements per page, independently of what the document reader reports. For each placement it SHALL record the page number, the placement rectangle in the document's coordinate space, and the pixel dimensions of the underlying image object. Enumeration SHALL NOT depend on the reader having detected anything on that page.

#### Scenario: Placements recorded on a page the reader found nothing on
- **WHEN** a page contains an embedded photograph and the document reader reports no figure on that page
- **THEN** that image's placement rectangle and pixel dimensions are still recorded for the page

#### Scenario: Page with no embedded images
- **WHEN** a page contains no embedded raster images
- **THEN** no placements are recorded for that page and processing continues without error

#### Scenario: Enumeration failure does not fail the run
- **WHEN** placements cannot be enumerated for one page
- **THEN** that page is recorded as not enumerable and the remaining pages are still processed

### Requirement: Placements are cross-checked against reader-detected figures
Each enumerated placement SHALL be compared against the figure polygons the document reader reported for the same page. A placement that substantially overlaps an already-detected figure SHALL NOT produce a duplicate figure record. A placement that overlaps no detected figure SHALL be treated as a recovery candidate. The overlap threshold SHALL be configurable.

#### Scenario: Placement matching a detected figure is not duplicated
- **WHEN** an enumerated placement substantially overlaps a figure the reader already reported
- **THEN** no additional figure record is created for that placement

#### Scenario: Unmatched placement becomes a recovery candidate
- **WHEN** an enumerated placement overlaps none of the figures the reader reported for that page
- **THEN** it is treated as a recovery candidate for that page

#### Scenario: Page where the reader detected nothing
- **WHEN** the reader reported no figures at all on a page that contains embedded image placements
- **THEN** every placement on that page is treated as a recovery candidate

### Requirement: Recovered figures carry a real bounding polygon
A recovered figure SHALL receive a bounding polygon derived from the PDF's own placement rectangle, expressed in the same coordinate space and units as reader-reported figure polygons. A recovered figure SHALL NOT be cited by page number alone.

#### Scenario: Recovered figure is citable by box
- **WHEN** a figure is recovered from an embedded image placement
- **THEN** its bounding polygon corresponds to that placement rectangle and is expressed in the same coordinate space as reader-reported polygons

#### Scenario: Recovered figure is croppable and describable
- **WHEN** a recovered figure passes qualification
- **THEN** it is cropped and processed by the same downstream steps as a reader-detected figure

### Requirement: Every figure record declares its detection provenance
Every figure record SHALL carry a provenance value identifying which detector produced it, distinguishing figures reported by the document reader from figures recovered by the placement cross-check. Run results SHALL report how many figures were recovered, so detection gaps are measurable rather than invisible.

#### Scenario: Reader-detected figure is attributed
- **WHEN** a figure originates from the document reader's reported figures
- **THEN** its record declares reader provenance

#### Scenario: Recovered figure is attributed
- **WHEN** a figure originates from the placement cross-check
- **THEN** its record declares recovery provenance

#### Scenario: Recovery count is reported
- **WHEN** a run completes on a document where figures were recovered
- **THEN** the run's step result reports the number of recovered figures

#### Scenario: No recoveries on a fully detected document
- **WHEN** every embedded placement matches a reader-detected figure
- **THEN** the run reports zero recovered figures and the figure set is unchanged

### Requirement: The cross-check is gated per page, not per document
Page classification SHALL be recorded per page rather than as a single document-level value. The cross-check SHALL be skipped on pages whose embedded images collectively cover substantially the whole page, because a scanned page is one full-page raster and is structurally indistinguishable from a deliberate full-bleed image. A document SHALL be able to contain both scanned and digitally-born pages and be handled correctly page by page.

#### Scenario: Scanned page is skipped
- **WHEN** a page's embedded images collectively cover substantially the entire page area
- **THEN** the cross-check is skipped for that page and no figure is recovered from it

#### Scenario: Partial-coverage image alongside text is checked
- **WHEN** a page contains live text and an embedded image covering part of the page
- **THEN** the cross-check runs for that page

#### Scenario: Mixed document is handled per page
- **WHEN** a document contains both scanned pages and digitally-born pages
- **THEN** each page is gated on its own classification rather than on a single document-wide classification

### Requirement: Recovery is optional and backward compatible
Recovery SHALL be controllable by configuration. When it is disabled, the pipeline SHALL behave as it did before this capability, indexing only reader-detected figures, and SHALL complete successfully.

#### Scenario: Recovery disabled
- **WHEN** recovery is disabled by configuration
- **THEN** only reader-detected figures are processed and the run completes successfully

#### Scenario: Non-PDF or unreadable source
- **WHEN** embedded placements cannot be read from the source document at all
- **THEN** the run continues using reader-detected figures only
