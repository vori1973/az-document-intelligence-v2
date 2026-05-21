## Why

When a pipeline run fails mid-way, there is no quick way to determine how far it progressed by looking at the blob container — you have to cross-reference Durable Functions instance state with App Insights logs. Adding a consistent `stepN-result.json` file written by each activity gives engineers an instant visual audit trail directly in the processing folder.

## What Changes

- Each pipeline activity (step2 through step7) writes a compact `stepN-result.json` summary blob to `processing/{doc_id}/{run_id}/` on successful completion, mirroring the `step1-result.json` that already exists.
- The summary captures only the key metrics logged to App Insights today (page count, table count, chunk count, duration, etc.) — no new data is computed, it is just persisted to blob storage.
- No existing blobs are renamed or removed (`adi-raw.json`, `adi-content.md`, `chunks.json`, etc. are unchanged).

## Capabilities

### New Capabilities

- `step-result-files`: Each pipeline activity writes a `stepN-result.json` status file to the run folder on success, providing a consistent, glanceable audit trail of pipeline progress directly in blob storage.

### Modified Capabilities

<!-- No existing spec-level requirements change — this is additive only. -->

## Impact

- **Code**: `src/activities/step2_adi.py`, `step3_router.py`, `step5_chunks.py`, `step6_embed.py`, `step7_search.py` — each gains a `_write_result` call at the end of its main function.
- **Blob storage**: Each run folder gains up to 6 new small JSON blobs (< 1 KB each). Storage cost is negligible.
- **No API changes**: The pipeline context, orchestrator, and trigger are untouched.
- **No schema changes**: AI Search index is unaffected.
