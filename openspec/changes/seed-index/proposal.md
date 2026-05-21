## Why

The load test tool cannot trigger HTTP 429 throttling against a small development
index because Azure Search throttling is resource-based — each query is too cheap
to saturate a replica. A utility to seed the index with synthetic chunks at realistic
scale (tens of thousands of documents) is needed to make the load test meaningful.

## What Changes

- New `scripts/load-test/seed_index.py` — generates and uploads synthetic chunks
  directly to the Azure AI Search index, bypassing the ingestion pipeline
- Synthetic chunks use random unit vectors (1536-dim) and placeholder text fields
  matching the existing `document-chunks` index schema
- Configurable chunk count (`--chunks`), batch size, and optional cleanup (`--delete`)
- `.gitignore` updated to exclude no new files (no output artifacts)

## Capabilities

### New Capabilities

- `seed-index`: Directly inject synthetic document chunks into Azure AI Search
  to simulate realistic index sizes for load testing without running the full
  ingestion pipeline

### Modified Capabilities

_(none — no changes to existing pipeline behaviour or specs)_

## Impact

- New file `scripts/load-test/seed_index.py` only
- Reuses `AZURE_SEARCH_ENDPOINT` and `AZURE_SEARCH_INDEX` env vars
- Reuses `Search Index Data Contributor` role already assigned to the dev identity
  (Data Reader is not sufficient — writes are required)
- No changes to pipeline code, shared modules, or existing index schema
- Synthetic chunks are prefixed (`synthetic-`) so they can be identified and
  deleted with `--delete` after load testing
