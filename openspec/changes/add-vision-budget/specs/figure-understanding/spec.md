## MODIFIED Requirements

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
