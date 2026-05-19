# az-document-intelligence-v2 — Design & Implementation Plan

## Overview

A production-grade, fully Azure-hosted redesign of the document intelligence pipeline. Documents are stored in Azure Blob Storage; any create/update/delete event automatically triggers the pipeline. All compute runs in Azure (Azure Durable Functions). No local execution required. Query/UI (Step 8) is excluded — use Azure AI Foundry Playground or a separate project.

---

## Key Decisions vs v1

| Topic | v1 | v2 |
|---|---|---|
| Language | TypeScript / Node.js | **Python** — better Azure AI SDK ecosystem, native Durable Functions support, richer PDF libraries |
| Execution | Local `npm run dev` | **Azure Durable Functions** (serverless, auto-scale) |
| Document input | Local file path argument | **Azure Blob Storage** — upload triggers the pipeline |
| Triggering | Manual | **Azure Event Grid** — BlobCreated / BlobDeleted events |
| Intermediate files | Local `output/` directory | **Blob Storage** `processing/{doc_id}/` container |
| Authentication | `.env` API keys | **Managed Identity** — no secrets in code; Key Vault for any remaining secrets |
| Delete/update handling | Not implemented | **Full stale-chunk cleanup** on delete and re-ingestion on update |
| Monitoring | Console logs + JSONL files | **Application Insights** — structured telemetry, pipeline run tracking |
| IaC | None | **Bicep** — all resources defined as code |
| Query / chat UI | Step 8 (standalone chatbot) | **Removed** — use Azure AI Foundry Playground |

---

## Architecture

```
User uploads PDF
      │
      ▼
Azure Blob Storage
  Container: documents/
      │
      ├── BlobCreated ──► Azure Event Grid ──► ingest_trigger (Function)
      │                                              │
      │                                              ▼
      │                                   Durable Orchestrator
      │                                   ┌─────────────────┐
      │                                   │ Activity: step1  │ pre-analysis (pypdf)
      │                                   │ Activity: step2  │ Azure Document Intelligence
      │                                   │ Activity: step3  │ confidence router
      │                                   │ Activity: step4  │ OCR model (fan-out per page)
      │                                   │ Activity: step5  │ build RAG chunks
      │                                   │ Activity: step6  │ embed (Azure OpenAI)
      │                                   │ Activity: step7  │ index (Azure AI Search)
      │                                   └─────────────────┘
      │                                        Artifacts stored in:
      │                                        Blob: processing/{doc_id}/{run_id}/
      │
      └── BlobDeleted ──► Azure Event Grid ──► delete_trigger (Function)
                                                     │
                                                     ▼
                                          Delete chunks from AI Search
                                          Delete processing/{doc_id}/ blobs
```

---

## Azure Resources Required

| Resource | SKU / Notes |
|---|---|
| Azure Blob Storage | Standard LRS — containers: `documents`, `processing` |
| Azure Event Grid System Topic | Blob storage events |
| Azure Functions (Flex Consumption or Premium) | Python 3.11, Durable Functions extension |
| Azure Document Intelligence | S0 tier |
| Azure AI Foundry (OCR model deployment) | Classic or serverless |
| Azure OpenAI | `text-embedding-ada-002`, optionally `gpt-4o-mini` |
| Azure AI Search | Standard S1 — vector index |
| Azure Key Vault | For any secrets not coverable by Managed Identity |
| Application Insights | Logs, traces, custom metrics |
| Azure Monitor | Alerts on pipeline failures |

---

## Project Structure

```
az-document-intelligence-v2/
│
├── infra/                          # Bicep IaC
│   ├── main.bicep                  # top-level deployment
│   ├── modules/
│   │   ├── storage.bicep
│   │   ├── functions.bicep
│   │   ├── event_grid.bicep
│   │   ├── search.bicep
│   │   ├── keyvault.bicep
│   │   └── monitoring.bicep
│   └── parameters/
│       ├── dev.bicepparam
│       └── prod.bicepparam
│
├── src/
│   ├── function_app.py             # Azure Functions entry points
│   ├── host.json                   # Functions runtime config
│   ├── requirements.txt
│   │
│   ├── triggers/
│   │   ├── ingest_trigger.py       # EventGrid BlobCreated → start orchestrator
│   │   └── delete_trigger.py       # EventGrid BlobDeleted → cleanup
│   │
│   ├── orchestrators/
│   │   └── pipeline_orchestrator.py  # Durable orchestrator: chains steps 1-7
│   │
│   ├── activities/                 # Durable activity functions (one per step)
│   │   ├── step1_preanalysis.py
│   │   ├── step2_adi.py
│   │   ├── step3_router.py
│   │   ├── step4_ocr.py            # fan-out: parallel per-page activity calls
│   │   ├── step5_chunks.py
│   │   ├── step6_embed.py
│   │   └── step7_search.py
│   │
│   ├── models/
│   │   └── types.py                # Pydantic models (replaces types.ts)
│   │
│   └── shared/
│       ├── blob_client.py          # Blob Storage helpers (read/write artifacts)
│       ├── auth.py                 # DefaultAzureCredential setup
│       └── telemetry.py            # Application Insights structured logging
│
├── tests/
│   ├── unit/                       # Unit tests per activity
│   └── integration/                # End-to-end test against real Azure resources
│
├── local.settings.json.example     # Template (never commit real settings)
├── .funcignore
├── .gitignore
└── README.md
```

---

## Implementation Phases

### Phase 0 — Repo & Tooling Setup
- [ ] Create `az-document-intelligence-v2/` directory structure
- [ ] Initialize Python virtual environment (Python 3.11)
- [ ] Initialize Azure Functions project (`func init --python`)
- [ ] Add `requirements.txt`:
  - `azure-functions`, `azure-durable-functions`
  - `azure-identity`, `azure-keyvault-secrets`
  - `azure-storage-blob`
  - `azure-ai-documentintelligence`
  - `azure-search-documents`
  - `openai` (Azure OpenAI SDK)
  - `pypdf` or `pymupdf` (PDF manipulation — replaces pdf-parse)
  - `pydantic` (data models)
  - `applicationinsights` or `opencensus-ext-azure`
- [ ] Configure `host.json` with Durable Functions extension, Application Insights
- [ ] Set up `.gitignore`, `.funcignore`
- [ ] Create `local.settings.json.example`
- [ ] Set up `pytest` + `pytest-asyncio` for tests

---

### Phase 1 — Infrastructure as Code (Bicep)
- [ ] **`storage.bicep`** — Storage account with two containers: `documents`, `processing`
  - Enable soft delete (document recovery)
  - Enable versioning on `documents` container (detect updates)
  - RBAC: assign `Storage Blob Data Contributor` to Function App Managed Identity
- [ ] **`event_grid.bicep`** — System topic on the storage account
  - Subscription for `BlobCreated` → ingest_trigger function endpoint
  - Subscription for `BlobDeleted` → delete_trigger function endpoint
  - Filter: only `.pdf` blobs in `documents/` container
- [ ] **`functions.bicep`** — Function App (Flex Consumption or Premium for VNet support)
  - System-assigned Managed Identity
  - App settings pointing to Key Vault references, not raw secrets
  - Python 3.11 runtime
  - Application Insights connection
- [ ] **`search.bicep`** — Azure AI Search
  - RBAC: assign `Search Index Data Contributor` to Function App MI
- [ ] **`keyvault.bicep`** — Key Vault
  - Store: ADI endpoint, Foundry endpoint/deployment name, AOAI endpoint/deployment names
  - Access policy for Function App MI
- [ ] **`monitoring.bicep`** — Application Insights + Log Analytics workspace
  - Custom alerts: pipeline failure rate, long-running orchestrations
- [ ] **`main.bicep`** — Compose all modules, output resource names/IDs
- [ ] Create `dev.bicepparam` and `prod.bicepparam`

---

### Phase 2 — Authentication & Shared Infrastructure
- [ ] **`auth.py`** — `DefaultAzureCredential` for all SDK clients
  - Works locally (az login / VS Code credential) and in Azure (Managed Identity)
  - No API keys in code or settings — all via RBAC or Key Vault references
- [ ] **`blob_client.py`** — helpers for:
  - `upload_artifact(doc_id, run_id, filename, content)` → `processing/` container
  - `download_artifact(doc_id, run_id, filename)` → bytes
  - `list_artifacts(doc_id, run_id)` → file list
  - `delete_doc_artifacts(doc_id)` → wipe `processing/{doc_id}/`
  - `download_document(blob_name)` → PDF bytes from `documents/` container
- [ ] **`telemetry.py`** — structured logging helpers
  - `log_step_start/end(step, doc_id, run_id, ...)`
  - `log_step_error(step, doc_id, exc, ...)`
  - Track custom metrics: pages processed, OCR routing rate, chunk count, token usage
- [ ] **`types.py`** — Pydantic models for all inter-step data contracts
  - `PreAnalysisResult`, `AdiResult`, `RoutingDecision`, `OcrPageResult`
  - `RagChunk`, `EmbeddedChunk`, `IndexResult`
  - `PipelineContext` (doc_id, run_id, blob_name, page_count, etc.)

---

### Phase 3 — Event Triggers
- [ ] **`ingest_trigger.py`** — Azure Function, EventGrid trigger
  - Receives `BlobCreated` event
  - Extracts `blob_name`, `blob_url`
  - Checks if this blob is a re-upload (same name, new content) → compute SHA-256, compare to stored doc_id
    - If same hash: skip (idempotent)
    - If new/changed: start orchestrator; if changed, first enqueue stale-chunk cleanup for old doc_id
  - Starts Durable orchestrator, passes `PipelineContext`
  - Logs pipeline start to Application Insights
- [ ] **`delete_trigger.py`** — Azure Function, EventGrid trigger
  - Receives `BlobDeleted` event
  - Resolves `doc_id` from blob name (lookup from a small metadata index or blob tag)
  - Deletes all AI Search chunks where `source_file == blob_name`
  - Deletes `processing/{doc_id}/` from blob storage
  - Logs cleanup to Application Insights
- [ ] Store `blob_name → doc_id` mapping as blob tags or a metadata JSON in `processing/` so delete can resolve the ID

---

### Phase 4 — Durable Orchestrator
- [ ] **`pipeline_orchestrator.py`** — chains activity functions
  ```python
  context.call_activity("step1_preanalysis", ctx)
  context.call_activity("step2_adi", ctx)
  context.call_activity("step3_router", ctx)
  # fan-out: parallel OCR per page
  tasks = [context.call_activity("step4_ocr_page", {**ctx, "page": p}) for p in ocr_pages]
  yield context.task_all(tasks)
  context.call_activity("step5_chunks", ctx)
  context.call_activity("step6_embed", ctx)
  context.call_activity("step7_search", ctx)
  ```
  - Each activity reads its inputs from blob artifacts written by the previous step
  - Orchestrator state managed by Durable Functions runtime (Azure Storage)
  - Retry policy: 3 retries with exponential backoff on transient failures

---

### Phase 5 — Pipeline Activities (Steps 1–7)

All activities read PDF/artifacts from Blob Storage and write outputs back to Blob Storage.

- [ ] **`step1_preanalysis.py`**
  - Download PDF bytes from `documents/` container
  - Compute SHA-256 → `doc_id`
  - Page count, text vs scanned heuristic (using `pypdf`)
  - Write `step1-result.json` to `processing/{doc_id}/{run_id}/`
  - Port logic from `step1-preanalysis.ts`

- [ ] **`step2_adi.py`**
  - Call Azure Document Intelligence (`prebuilt-layout`, markdown output)
  - Span-matched table confidence (port from `step2-adi.ts`)
  - Figure extraction
  - Write `adi-raw.json`, `adi-content.md` to blob
  - Log API timing, page/table/figure counts

- [ ] **`step3_router.py`**
  - Port confidence-based routing logic from `step3-confidence-router.ts`
  - All routing rules preserved: min cell confidence, rowSpan, mixed orientation, figures
  - Write `routing.json` to blob

- [ ] **`step4_ocr.py`** (fan-out pattern — two activities per page)

  **Why two activities:** if OCR fails (rate limit, timeout), Durable retries only the OCR call — no re-extracting or re-uploading the page PDF.

  - **Activity A — `extract_page`** (one per routed page, run in parallel):
    - Downloads full PDF bytes from `documents/` blob (or caches in orchestrator context)
    - Extracts page N as a single-page PDF using `PyMuPDF`
    - Uploads `processing/{doc_id}/{run_id}/pages/page-{N}.pdf` to blob
    - Generates a short-lived SAS URL (1-hour expiry) for that blob
    - Returns the SAS URL

  - **Activity B — `ocr_page`** (one per routed page, run after Activity A):
    - Receives the SAS URL from Activity A
    - Calls Mistral OCR API with `document_url = "<https blob SAS URL>"` — **no base64 encoding**
      - The Mistral OCR `document_url` field accepts both `data:` URIs and plain HTTPS URLs
      - SAS URL approach: ~33% smaller HTTP payload, no memory pressure, cleaner retry story
    - Writes `ocr-page-{N}.md` to blob
    - Writes `p{N}-img-{M}.jpeg` images to blob (extracted from `include_image_base64` response)
    - On Durable retry (rate limit / transient error): SAS URL is regenerated fresh — no re-extraction needed

  **Fan-out in orchestrator:**
  ```python
  # Phase 1: extract all pages in parallel
  extract_tasks = [context.call_activity("extract_page", {..., "page": p}) for p in ocr_pages]
  sas_urls = yield context.task_all(extract_tasks)   # dict: page → SAS URL

  # Phase 2: OCR all pages in parallel (with Foundry rate-limit concurrency cap)
  ocr_tasks = [context.call_activity("ocr_page", {"sas_url": sas_urls[p], "page": p}) for p in ocr_pages]
  yield context.task_all(ocr_tasks)
  ```

  **Note on concurrency:** Foundry has per-deployment rate limits. Cap parallel OCR calls using a Durable fan-out with `task_all` + a semaphore, or chunk the fan-out in batches of N (e.g. 5 concurrent pages).

- [ ] **`step5_chunks.py`**
  - Read ADI result + OCR markdowns from blob
  - Port all chunking logic from `step5-index.ts`:
    - `table_row` chunks with fused headers
    - `paragraph` sliding window (~500 tokens, ~100 overlap)
    - `figure` chunks
    - ADI cell grid normalization (`buildAdiCellGrid`, `normalizeAdiGrid`)
    - OCR-ADI table alignment, row-count mismatch fallback
  - Write `chunks.json` to blob
  - Write `tables-debug.md`, `tables-flags.md`, `tables-stats.md` to blob

- [ ] **`step6_embed.py`**
  - Read `chunks.json` from blob
  - Batch embed via Azure OpenAI `text-embedding-ada-002` (batches of 100)
  - Write `chunks-embedded.json` to blob
  - Log token usage to Application Insights

- [ ] **`step7_search.py`**
  - Read `chunks-embedded.json` from blob
  - Upsert into Azure AI Search HNSW cosine vector index
  - Port index schema from `step7-search.ts`
  - Idempotent: upsert by `chunk_id`
  - Log upload batches to Application Insights

---

### Phase 6 — Stale Chunk Cleanup
- [ ] Implement `cleanup_document(doc_id, source_file)` shared utility
  - Query AI Search for all chunks with matching `source_file` or `document_id`
  - Batch delete from index
  - Used by both `delete_trigger` and re-ingestion flow in `ingest_trigger`
- [ ] On update (BlobCreated on existing blob name with new content):
  1. Resolve old `doc_id` from stored mapping
  2. Run cleanup for old `doc_id`
  3. Start fresh ingestion for new `doc_id`

---

### Phase 7 — Monitoring & Observability
- [ ] Application Insights custom events per pipeline step (start, end, error)
- [ ] Custom metrics:
  - `pipeline.duration_seconds` (per document)
  - `pipeline.pages_total`, `pipeline.ocr_pages`, `pipeline.adi_pages`
  - `pipeline.chunks_created`, `pipeline.tokens_used`
  - `pipeline.failures` (per step)
- [ ] Azure Monitor alert rules:
  - Pipeline failure rate > 5% in 1 hour
  - Orchestration stuck > 30 minutes
- [ ] Durable Functions status endpoint for pipeline run visibility

---

### Phase 8 — Testing
- [ ] **Unit tests** for each activity (mock Azure clients)
  - Routing logic (deterministic, no external calls)
  - Chunk building logic
  - Cell grid normalization
- [ ] **Integration tests** (run against real Azure dev resources)
  - Upload a known PDF → verify chunks appear in AI Search
  - Delete the PDF → verify chunks removed
  - Re-upload modified PDF → verify old chunks removed, new chunks indexed
- [ ] Port existing sample PDFs (`sample-tables.pdf`, `embedded-images-tables.pdf`) as test fixtures
- [ ] CI pipeline (GitHub Actions) running unit tests on every PR

---

### Phase 9 — Documentation & Cleanup
- [ ] `README.md` — architecture diagram, prerequisites, deployment steps, local dev guide
- [ ] Document Bicep deployment: `az deployment sub create ...`
- [ ] Document local testing with Azurite (local storage emulator) + Functions Core Tools
- [ ] Document how to use AI Foundry Playground to query the indexed data

---

## What Was Not Included (Compared to v1)

| v1 Item | Status |
|---|---|
| Step 8 — Query/chat REPL | **Removed** — use Azure AI Foundry Playground or build as a separate project |
| Local `output/` directory | Replaced by Blob Storage `processing/` container |
| `.env` file with API keys | Replaced by Managed Identity + Key Vault |
| `npm run dev` local execution | Replaced by Event Grid triggers; local dev uses Functions Core Tools |

---

## Open Questions / Decisions Needed

1. **Compute tier**: Flex Consumption (cold start acceptable?) vs Premium (always warm, needed for VNet). For a POC, Flex Consumption is fine.
2. **OCR model fan-out concurrency**: How many parallel page-level OCR calls? Foundry has rate limits — may need a semaphore or batching strategy.
3. **PDF extraction library**: `pypdf` (pure Python, lightweight) vs `PyMuPDF/fitz` (faster, C extension, better image extraction). PyMuPDF is recommended for image-heavy documents.
4. **Blob versioning vs tagging for update detection**: Blob versioning adds cost; alternatively store `{blob_name: doc_id}` as a JSON file in `processing/` container.
5. **AI Search index schema**: Carry over existing schema from v1 or revise field names/types?
6. **Multi-region**: Out of scope for POC — single region deployment.
