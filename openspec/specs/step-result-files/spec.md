## Purpose

Makes each pipeline step's success independently verifiable from storage alone, so a partial or failed run can be diagnosed by inspecting the run folder without depending on application telemetry.

## Requirements

### Requirement: Step result file written on activity success
Each pipeline activity (step2 through step7) SHALL write a JSON file named `stepN-result.json` to `processing/{doc_id}/{run_id}/` upon successful completion. The file content SHALL match the key metrics emitted to App Insights by that step.

#### Scenario: step2_adi writes result file after ADI completes
- **WHEN** `step2_adi` successfully analyzes a document
- **THEN** `processing/{doc_id}/{run_id}/step2-result.json` is created with fields: `pages`, `tables`, `figures`, `low_conf_pages`, `duration_ms`

#### Scenario: step3_router writes result file after routing decision
- **WHEN** `step3_router` successfully determines routing for all pages
- **THEN** `processing/{doc_id}/{run_id}/step3-result.json` is created with fields: `adi_only` (page list), `ocr_pages` (page list), `low_conf_tables`, `ocr_enabled`

#### Scenario: step5_chunks writes result file after chunking
- **WHEN** `step5_chunks` successfully builds all chunks
- **THEN** `processing/{doc_id}/{run_id}/step5-result.json` is created with fields: `paragraphs`, `table_rows`, `figures`, `total`

#### Scenario: step6_embed writes result file after embedding
- **WHEN** `step6_embed` successfully generates all embeddings
- **THEN** `processing/{doc_id}/{run_id}/step6-result.json` is created with fields: `chunks`, `batches`, `duration_ms`

#### Scenario: step7_search writes result file after indexing
- **WHEN** `step7_search` successfully indexes all chunks
- **THEN** `processing/{doc_id}/{run_id}/step7-result.json` is created with fields: `indexed`, `index_action` (`created` or `updated`), `duration_ms`

### Requirement: Result file absent when step fails or has not run
A `stepN-result.json` file SHALL NOT be written when an activity raises an exception. The absence of the file SHALL be interpretable as "step did not complete successfully."

#### Scenario: No result file after activity failure
- **WHEN** a pipeline activity raises an exception before completing
- **THEN** no `stepN-result.json` file exists for that step in the run folder

#### Scenario: Partial run folder reflects progress
- **WHEN** a pipeline run fails at step5
- **THEN** `step1-result.json`, `step2-result.json`, `step3-result.json` are present and `step5-result.json`, `step6-result.json`, `step7-result.json` are absent

### Requirement: Existing blobs are unchanged
The addition of `stepN-result.json` files SHALL NOT rename, remove, or alter the content of existing blobs (`adi-raw.json`, `adi-content.md`, `adi-results.json`, `chunks.json`, `chunks-embedded.json`, `routing.json`, `tables-flags.md`, `tables-stats.md`).

#### Scenario: Existing blob content preserved
- **WHEN** a pipeline run completes successfully
- **THEN** all previously existing domain blobs are present with their original content and the new `stepN-result.json` files are also present alongside them
