## MODIFIED Requirements

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
