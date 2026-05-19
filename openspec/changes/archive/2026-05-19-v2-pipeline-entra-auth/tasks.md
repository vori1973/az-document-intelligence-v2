# Tasks: v2 Pipeline with Entra Authentication

## Phase 0 — Project Setup
- [x] 0.1 Create directory structure
- [x] 0.2 Initialize OpenSpec
- [x] 0.3 Write requirements.txt
- [x] 0.4 Write host.json (Durable Functions extension)
- [x] 0.5 Write .gitignore, .funcignore
- [x] 0.6 Write local.settings.json.example

## Phase 1 — IaC (Bicep)
- [x] 1.1 storage.bicep — containers, soft delete, RBAC
- [x] 1.2 event_grid.bicep — system topic, subscriptions
- [x] 1.3 functions.bicep — Function App, Managed Identity, Python 3.11
- [x] 1.4 search.bicep — AI Search, RBAC
- [x] 1.5 keyvault.bicep — Key Vault, access policy
- [x] 1.6 monitoring.bicep — App Insights, Log Analytics
- [x] 1.7 main.bicep — compose all modules
- [x] 1.8 dev.bicepparam, prod.bicepparam

## Phase 2 — Shared Infrastructure
- [x] 2.1 auth.py — DefaultAzureCredential
- [x] 2.2 blob_client.py — artifact read/write helpers
- [x] 2.3 telemetry.py — App Insights structured logging
- [x] 2.4 types.py — Pydantic models

## Phase 3 — Event Triggers
- [x] 3.1 ingest_trigger.py — BlobCreated → start orchestrator
- [x] 3.2 delete_trigger.py — BlobDeleted → cleanup

## Phase 4 — Durable Orchestrator
- [x] 4.1 pipeline_orchestrator.py — chain steps 1-7, fan-out OCR

## Phase 5 — Activity Functions
- [x] 5.1 step1_preanalysis.py — SHA-256, page count, text heuristic
- [x] 5.2 step2_adi.py — Azure Document Intelligence, markdown, figures
- [x] 5.3 step3_router.py — confidence-based routing
- [x] 5.4 step4_ocr.py — extract_page + ocr_page (SAS URL, fan-out)
- [x] 5.5 step5_chunks.py — table_row + paragraph + figure chunks
- [x] 5.6 step6_embed.py — Azure OpenAI embeddings
- [x] 5.7 step7_search.py — AI Search upsert

## Phase 6 — Stale Chunk Cleanup
- [x] 6.1 cleanup_document utility in shared/

## Phase 7 — Function App Entry Point
- [x] 7.1 function_app.py — register all functions

## Phase 8 — Testing
- [x] 8.1 Unit tests for router logic
- [x] 8.2 Unit tests for chunk building
- [ ] 8.3 Integration test: upload → verify chunks in Search
- [ ] 8.4 Integration test: delete → verify chunks removed

## GitHub Issue
- [x] Create issue: "Entra auth: replace Foundry key with Managed Identity once supported"
