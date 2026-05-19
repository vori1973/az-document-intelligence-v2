# Deployment Guide

Two deployment paths are supported: **VS Code** (recommended for first-time setup) and the **CLI script** (CI/CD or repeatable deploys).

---

## Prerequisites

| Tool | Required for |
|------|-------------|
| [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) | Both paths |
| [Azure Functions Core Tools v4](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local) | Both paths (code deploy) |
| [jq](https://jqlang.github.io/jq/) | Script path only |
| VS Code + [Azure Tools extension pack](https://marketplace.visualstudio.com/items?itemName=ms-vscode.vscode-node-azure-pack) | VS Code path |

**Authenticate before starting either path:**

```bash
az login
az account set --subscription "<your-subscription-id>"
```

---

## Path A — VS Code (Azure Extension)

### 1. Deploy Bicep infrastructure

1. Open the **Azure** panel in VS Code (the Azure icon in the sidebar)
2. Under **Resources**, right-click your subscription → **Create Resource Group**
   - Name: `docintv2-dev-rg`
   - Region: `East US`
3. Right-click the resource group → **Deploy Bicep File...**
   - Template: `infra/main.bicep`
   - Parameters: `infra/parameters/dev.bicepparam`
4. VS Code will show deployment progress in the Output panel (~5–10 min)

### 2. Store the Foundry key in Key Vault

> Skip this step — `ocrEnabled = 'false'` so no Foundry key is needed yet.
> The deploy script stores a placeholder automatically; VS Code path requires one manual step:

1. In the Azure panel, expand your resource group → **Key Vaults** → `docintv2-dev-kv`
2. Click **Secrets** → **+ Create/Import**
   - Name: `foundry-key`
   - Value: `placeholder-ocr-disabled`

### 3. Deploy Function App code

1. In VS Code, open the **Azure** panel → **Workspace** (local)
2. Under **Function App**, click the deploy button (cloud with up-arrow)
3. Select the Function App: `docintv2-dev-func`
4. Confirm "Deploy to Function App" in the dialog
5. Watch the Output panel for `Deployment successful`

### 4. Verify

1. In the Azure panel, expand `docintv2-dev-func` → **Functions**
2. You should see: `ingest_trigger`, `delete_trigger`, `pipeline_orchestrator_fn`, `cleanup_orchestrator_fn`, and all activity functions (`step1_preanalysis`, `step2_adi`, `step3_router`, `extract_page`, `ocr_page`, `step5_chunks`, `step6_embed`, `step7_search`, `cleanup_activity`)
3. Upload a test PDF to the `documents` container (Azure panel → Storage Accounts → Blob Containers → documents → Upload)
4. Watch the pipeline execute: Function App → **Monitor** in the Azure portal

---

## Path B — CLI Script

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh dev
```

The script runs all steps end-to-end: resource group → Bicep deploy → Key Vault secret → `func publish`.

See inline comments in `scripts/deploy.sh` for details.

---

## What gets deployed

All resources are created inside `docintv2-dev-rg`. All service-to-service authentication uses **Managed Identity (RBAC)** — no connection strings or API keys in application config.

### Compute

| Resource | Type | Role |
|----------|------|------|
| `docintv2-dev-func` | Function App (Flex Consumption) | Hosts all pipeline logic. Scales to zero when idle. Contains `ingest_trigger`, `delete_trigger`, the Durable orchestrator, and one activity function per pipeline step. |
| `docintv2-dev-plan` | App Service Plan (FC1) | The Flex Consumption billing/scaling plan that backs the Function App. Not a dedicated server. |

### Storage

| Resource | Type | Role |
|----------|------|------|
| `docintv2devst` | Storage Account (Standard LRS) | Central data store for the pipeline. Three containers: |

**Blob containers inside `docintv2devst`:**

| Container | Purpose |
|-----------|---------|
| `documents/` | Drop zone for PDF uploads. Event Grid monitors this container for new and deleted files. |
| `processing/` | Intermediate pipeline artifacts keyed as `processing/{doc_id}/{run_id}/`. Holds ADI JSON output, extracted page images, OCR results, routing decisions, and final chunks. |
| `deployments/` | Used internally by Flex Consumption to store and retrieve the deployed function code package. Must exist before `func publish`. |

### AI Services

| Resource | Type | Role |
|----------|------|------|
| `docintv2-dev-adi` | Azure Document Intelligence | Runs the `prebuilt-layout` model on each PDF page (step 2). Extracts paragraphs, tables with per-cell confidence scores, figure locations, and markdown-formatted text. Confidence scores drive the routing decision in step 3. |
| `docintv2-dev-oai` | Azure OpenAI | Hosts `text-embedding-ada-002` (step 6). Converts each text chunk into a 1536-dimensional vector embedding that gets stored in AI Search for semantic similarity queries. |

### Search & Retrieval

| Resource | Type | Role |
|----------|------|------|
| `docintv2-dev-search` | Azure AI Search (Standard S1) | The pipeline's output destination (step 7). Stores processed chunks — paragraphs, table rows, figure captions — with their vector embeddings. Supports both vector similarity search and semantic re-ranking. Your application queries this index to find relevant content from uploaded documents. |

### Eventing

| Resource | Type | Role |
|----------|------|------|
| `docintv2devst-topic` | Event Grid System Topic | Listens to blob events on the storage account. Routes `BlobCreated` events on `documents/*.pdf` to `ingest_trigger` (starts pipeline), and `BlobDeleted` events to `delete_trigger` (removes chunks from search index). Makes the pipeline fully event-driven — no polling or manual triggering required. |

### Security

| Resource | Type | Role |
|----------|------|------|
| `docintv2-dev-kv` | Key Vault (Standard, RBAC) | Stores secrets that cannot use managed identity. Currently one secret: `foundry-key` (Mistral OCR API key — placeholder while OCR is disabled). All other services authenticate via managed identity with no secrets needed. |

**Managed Identity RBAC assignments** (granted to the Function App's system-assigned identity):

| Service | Role | Why |
|---------|------|-----|
| Storage | Blob Data Contributor | Read uploaded PDFs, write/read processing artifacts |
| Storage | Blob Delegator | Generate user-delegation SAS URLs for Mistral OCR page images |
| Document Intelligence | Cognitive Services User | Call the ADI analysis API |
| Azure OpenAI | Cognitive Services OpenAI User | Call the embedding model |
| AI Search | Search Index Data Contributor | Read and write index documents |
| AI Search | Search Service Contributor | Create and update the index schema |
| Key Vault | Key Vault Secrets User | Read the Foundry API key at runtime |

Your deploying user is granted **Key Vault Secrets Officer** by Bicep so the deploy script can write the `foundry-key` secret during deployment.

### Monitoring

| Resource | Type | Role |
|----------|------|------|
| `docintv2-dev-ai` | Application Insights | Collects logs, traces, exceptions, and custom metrics from the Function App. Every pipeline step logs start/end/error events and durations here. |
| `docintv2-dev-logs` | Log Analytics Workspace | Backend store for Application Insights telemetry. Enables KQL queries for long-term retention and cross-resource diagnostics. |

### Data flow

```
PDF uploaded to documents/
         |
         v
   Event Grid topic  (BlobCreated)
         |
         v
   ingest_trigger
         |
         v
   pipeline_orchestrator  (Durable Functions)
         |
         +-- step1_preanalysis  --> SHA-256, page count, text heuristic --> processing/
         +-- step2_adi          --> Document Intelligence (prebuilt-layout) --> processing/
         +-- step3_router       --> confidence check, decide pages for OCR
         +-- [fan-out] extract_page × N  --> page images --> processing/
         +-- [fan-out] ocr_page × N      --> Mistral OCR [disabled: skipped, ADI covers all pages]
         +-- step5_chunks       --> paragraph / table-row / figure chunks --> processing/
         +-- step6_embed        --> OpenAI text-embedding-ada-002 embeddings
         +-- step7_search       --> index chunks + embeddings into AI Search
```

---

## Monitoring

**VS Code:** Azure panel → Function App → right-click → **Open in Portal** → Monitor

**CLI:**
```bash
# List orchestration instances
az durable list-instances \
  --resource-group docintv2-dev-rg \
  --app docintv2-dev-func

# Live logs (App Insights)
az monitor app-insights query \
  --apps docintv2-dev-ai \
  --resource-group docintv2-dev-rg \
  --analytics-query "traces | where timestamp > ago(30m) | order by timestamp desc | take 50" \
  --output table
```

---

## Enabling Mistral OCR later

Once your Azure AI Foundry / Mistral subscription is resolved:

1. Create an Azure AI Foundry resource in the portal
2. Deploy the `mistral-ocr` model (Model catalog → Classic deployment)
3. Copy the endpoint URL
4. Update `infra/parameters/dev.bicepparam`:
   ```bicep
   param foundryEndpoint = 'https://your-resource.services.ai.azure.com'
   param ocrEnabled      = 'true'
   ```
5. Re-deploy infrastructure (either path above)
6. Update the `foundry-key` secret in Key Vault with the real API key

---

## Running tests

```bash
# Activate venv (first time: python3 -m venv .venv && .venv/bin/pip install pytest pytest-asyncio pydantic)
source .venv/bin/activate

# Unit tests (no Azure connection required)
pytest tests/unit/ -v

# Integration tests (requires deployed resources)
RESOURCE_GROUP=docintv2-dev-rg \
FUNCTION_APP=docintv2-dev-func \
pytest tests/integration/ -v
```
