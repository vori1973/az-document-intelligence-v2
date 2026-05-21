<div align="center">

# Azure Document Intelligence Pipeline v2

Event-driven, fully Azure-hosted document ingestion pipeline that extracts, chunks, embeds, and indexes PDF content into Azure AI Search — triggered automatically on upload, updated on re-upload, and cleaned up on delete.

![Azure](https://img.shields.io/badge/Azure-0078D4?style=for-the-badge&logo=microsoft-azure&logoColor=white)
![Python](https://img.shields.io/badge/Python_3.13-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Azure Functions](https://img.shields.io/badge/Durable_Functions-0062AD?style=for-the-badge&logo=microsoft-azure&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)

</div>

---

## 🌟 Key Capabilities

| Capability | Detail |
|------------|--------|
| **Fully event-driven** | Upload a PDF → pipeline starts automatically via Event Grid. Delete it → chunks and artifacts are removed. No manual triggering. |
| **Zero secrets in config** | All service auth uses Managed Identity (RBAC). Only the Mistral OCR key lives in Key Vault, and only when OCR is enabled. |
| **Confidence-based routing** | Each page is scored by Azure Document Intelligence. Pages with low table confidence, row-spanning cells, mixed orientation, or figure overlap are routed to Mistral OCR for better extraction. Currently disabled (ADI-only mode). |
| **Durable orchestration** | Each pipeline step is an independent Azure Durable Functions activity. Retries, fan-out, and state are managed by the runtime — no custom queuing code. |
| **Idempotent re-ingestion** | Re-uploading a changed PDF detects the content change (SHA-256), cleans up stale chunks for the old version, and starts a fresh pipeline run. |
| **Scales to zero** | Runs on Flex Consumption — no idle compute cost. |

### v2 vs v1

| Topic | v1 | v2 |
|-------|----|----|
| Language | TypeScript / Node.js | **Python 3.13** |
| Execution | `npm run dev` (local) | **Azure Durable Functions** (serverless) |
| Triggering | Manual CLI | **Azure Event Grid** (BlobCreated / BlobDeleted) |
| Authentication | `.env` API keys | **Managed Identity** — RBAC throughout |
| Intermediate storage | Local `output/` directory | **Blob Storage** `processing/{doc_id}/{run_id}/` |
| Delete/update handling | Not implemented | **Full stale-chunk cleanup** on delete and re-upload |
| Monitoring | Console + JSONL files | **Application Insights** — structured telemetry |
| Infrastructure | None | **Bicep** — all resources as code |
| Query / chat UI | Step 8 (local REPL) | Removed — use Azure AI Foundry Playground |

---

## 🏗️ Architecture

```
INGEST PATH
-----------
PDF uploaded to documents/
         |
         v
   Event Grid  (BlobCreated, ingest-pdf subscription)
         |
         v
   ingest_trigger
     · compute SHA-256 → doc_id
     · idempotency check (skip if identical content)
     · if re-upload: queue cleanup_orchestrator for old doc_id
         |
         v
   pipeline_orchestrator  (Durable Functions)
         |
         +-- step1_preanalysis  → SHA-256 verify, page count, text heuristic
         +-- step2_adi          → Document Intelligence prebuilt-layout
         +-- step3_router       → confidence check, decide which pages need OCR
         +-- [fan-out] extract_page × N  → extract page PDFs → processing/
         +-- [fan-out] ocr_page × N      → Mistral OCR [disabled: ADI covers all pages]
         +-- step5_chunks       → paragraph / table-row / figure chunks
         +-- step6_embed        → OpenAI text-embedding-ada-002 (1536-dim)
         +-- step7_search       → create/update index schema, upsert chunks

DELETE PATH
-----------
PDF deleted from documents/
         |
         v
   Event Grid  (BlobDeleted, delete-pdf subscription)
         |
         v
   delete_trigger
         +-- resolve doc_id via O(1) name-index lookup
         +-- delete all AI Search chunks where document_id matches
         +-- delete all processing/ artifacts for that doc_id
```

All intermediate artifacts are stored in Blob Storage under `processing/{doc_id}/{run_id}/` and cleaned up on delete.

---

## 🔒 Security

All service-to-service auth uses the Function App's **system-assigned Managed Identity** — no connection strings or API keys in application config.

| Service | Role |
|---------|------|
| Storage | Blob Data Contributor, Blob Delegator, Table Data Contributor, Queue Data Contributor |
| Azure Document Intelligence | Cognitive Services User |
| Azure OpenAI | Cognitive Services OpenAI User |
| AI Search | Search Index Data Contributor, Search Service Contributor |
| Key Vault | Key Vault Secrets User |

`AzureWebJobsStorage` uses `AzureWebJobsStorage__accountName` (identity-based, no connection string). The deploying user is granted **Key Vault Secrets Officer** by Bicep to write the `foundry-key` secret during deployment.

---

## 🚀 Quick Start

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for full instructions.

Two paths:

**Path A — VS Code** (recommended for first-time setup)
1. Deploy Bicep via VS Code Azure extension
2. Store `foundry-key` placeholder in Key Vault
3. Deploy function code via VS Code
4. Wire Event Grid subscriptions (CLI commands in DEPLOYMENT.md)

**Path B — CLI script** (CI/CD or repeatable deploys)
```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh dev
```
Runs all steps end-to-end: resource group → Bicep → Key Vault secret → `func publish` → Event Grid subscriptions.

---

## 📁 Project Structure

```
az-document-intelligence-v2/
  📄 README.md
  📄 DEPLOYMENT.md          — deployment guide (both paths, RBAC, monitoring)
  📄 TODO.md                — original design & implementation plan
  |
  📁 infra/                 — Bicep IaC
  |   📄 main.bicep
  |   📁 modules/
  |       storage.bicep · functions.bicep · search.bicep
  |       keyvault.bicep · event_grid.bicep · monitoring.bicep
  |       adi.bicep · adi_rbac.bicep · openai.bicep · openai_rbac.bicep
  |   📁 parameters/
  |       dev.bicepparam
  |
  📁 src/                   — Function App (Python 3.13)
  |   📄 function_app.py    — registers all triggers, orchestrators, activities
  |   📄 host.json
  |   📄 requirements.txt
  |   |
  |   📁 triggers/
  |   |   ingest_trigger.py · delete_trigger.py
  |   |
  |   📁 orchestrators/
  |   |   pipeline_orchestrator.py
  |   |
  |   📁 activities/
  |   |   step1_preanalysis.py · step2_adi.py · step3_router.py
  |   |   step4_ocr.py · step5_chunks.py · step6_embed.py · step7_search.py
  |   |
  |   📁 shared/
  |   |   auth.py · blob_client.py · telemetry.py
  |   |
  |   📁 models/
  |       types.py
  |
  📁 scripts/
  |   deploy.sh
  |
  |   📁 load-test/           — Azure AI Search load testing & advisor tools
  |       📄 README.md        — full usage guide
  |       seed_index.py       — inject synthetic chunks to reach realistic index size
  |       load_test.py        — async concurrent load runner (concurrency, profile, retries)
  |       advisor.py          — reads results/ → prints replica recommendations
  |       embed_queries.py    — one-time: pre-embed queries via Azure OpenAI
  |       📁 kql/             — Log Analytics queries (throttling, latency, saturation)
  |
  📁 tests/
      📁 unit/ · 📁 integration/
```

---

## 🧪 Load Testing

`scripts/load-test/` contains an educational load-testing toolkit for the Azure AI Search index.

| Tool | Purpose |
|------|---------|
| `seed_index.py` | Inject synthetic chunks to simulate realistic index sizes (50k–200k docs) before load testing. Uses random unit vectors — no pipeline required. |
| `load_test.py` | Async concurrent load runner. Configurable concurrency, duration, query profile (vector / hybrid / semantic), and SDK retry behaviour. |
| `advisor.py` | Reads `results/` and prints replica scaling recommendations with threshold rules. |
| `kql/` | Log Analytics queries for throttling rate, latency trend, and the replica saturation pattern (QPS plateau + latency climb). |

See **[scripts/load-test/README.md](scripts/load-test/README.md)** for the full workflow including RBAC setup, seeding guidance, and how to interpret results.

> **Note:** Azure Search S1 degrades under load via latency (queuing), not HTTP 429s.
> The saturation signal is QPS plateauing while p95 climbs — visible in `saturation.kql`.

---

## 📊 Monitoring

**Portal:** Azure portal → Function App `docintv2-dev-func` → Monitor

**CLI — live traces:**
```bash
az monitor app-insights query \
  --apps docintv2-dev-ai \
  --resource-group docintv2-dev-rg \
  --analytics-query "traces | where timestamp > ago(30m) | order by timestamp desc | take 50" \
  --output table
```

**CLI — orchestration instances:**
```bash
az durable list-instances \
  --resource-group docintv2-dev-rg \
  --app docintv2-dev-func
```

Every pipeline step logs `step_start`, `step_end`, and `step_error` events with `doc_id`, `run_id`, duration, and step-specific metrics (pages, chunks, tokens, etc.) to Application Insights.

---

## 🔧 Confidence-Based Routing (Step 3)

Routing logic is preserved 1:1 from v1 — deterministic, no LLM involved:

| Signal | Action |
|--------|--------|
| Min cell confidence < 0.75 | Page → OCR |
| Body cell with `rowSpan > 1` | Page → OCR |
| Mixed orientation detected | Page → OCR |
| Figure overlapping a table (`OCR_FIGURE_ROUTING=true`) | Page → OCR |
| Otherwise | ADI output accepted as-is |

Currently `OCR_ENABLED=false` — ADI handles all pages. Mistral OCR activates when a Foundry subscription is available (see [Enabling Mistral OCR](DEPLOYMENT.md#enabling-mistral-ocr-later)).

---

## 🔗 Evolved From

This project is v2 of [az-document-intelligence](../az-document-intelligence) — a local TypeScript pipeline. v2 ports the extraction and chunking logic to Python and lifts it fully into Azure: Event Grid replaces the CLI entrypoint, Durable Functions replace the sequential orchestrator, Blob Storage replaces the local `output/` directory, and Managed Identity replaces `.env` API keys.

The routing rules, chunk schema, ADI normalization passes, and AI Search index structure are preserved from v1.
