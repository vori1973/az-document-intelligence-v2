# Design: v2 Pipeline with Entra Authentication

## Authentication Architecture

All Azure SDK clients use `DefaultAzureCredential` from `azure-identity`. This credential chain:
1. Locally: picks up `az login` credentials or VS Code credentials
2. In Azure: uses the Function App's system-assigned Managed Identity

No API keys are stored anywhere. Access is granted via Azure RBAC roles:

| Identity | Resource | Role |
|---|---|---|
| Function App MI | Storage Account | Storage Blob Data Contributor |
| Function App MI | Azure AI Search | Search Index Data Contributor |
| Function App MI | Azure Document Intelligence | Cognitive Services User |
| Function App MI | Azure OpenAI | Cognitive Services OpenAI User |
| Function App MI | Key Vault | Key Vault Secrets User |
| Function App MI | Foundry (AI Services) | Cognitive Services User |

## Entra Auth Implementation

```python
# src/shared/auth.py
from azure.identity import DefaultAzureCredential

def get_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential()
```

All SDK clients constructed with this credential — never with API keys.

## Pipeline Flow

```
BlobCreated event
    └── ingest_trigger (EventGrid Function)
            └── Durable Orchestrator: pipeline_orchestrator
                    ├── step1_preanalysis   (download PDF, SHA-256 doc_id, page count)
                    ├── step2_adi           (Azure Document Intelligence, markdown output)
                    ├── step3_router        (confidence-based routing decision)
                    ├── [fan-out] extract_page × N  (PyMuPDF page extraction → Blob SAS URL)
                    ├── [fan-out] ocr_page × N      (Mistral OCR via SAS URL)
                    ├── step5_chunks        (build RAG chunks from ADI + OCR results)
                    ├── step6_embed         (Azure OpenAI embeddings, batches of 100)
                    └── step7_search        (upsert into Azure AI Search HNSW index)

BlobDeleted event
    └── delete_trigger
            └── cleanup_document(doc_id)   (delete Search chunks + processing blobs)
```

## Key Design Decisions

### SAS URL for Mistral OCR (step4)
Rather than base64-encoding entire PDFs, step4 generates a short-lived (1h) SAS URL
for each extracted page and passes it to Mistral's `document_url` field. This reduces
HTTP payload by ~33% and enables clean Durable retry semantics.

### Idempotency
- doc_id is SHA-256 of the PDF content → same file always produces the same doc_id
- Search upsert uses `@search.action: "mergeOrUpload"` by chunk_id
- Re-uploads with same hash are detected and skipped

### Artifact storage
All inter-step artifacts stored in `processing/{doc_id}/{run_id}/` in Blob Storage:
- `step1-result.json`, `adi-raw.json`, `adi-content.md`, `routing.json`
- `pages/page-{N}.pdf` (extracted single-page PDFs)
- `ocr-page-{N}.md`, `p{N}-img-{M}.jpeg`
- `chunks.json`, `chunks-embedded.json`

### OCR model
Step4 uses Mistral OCR via Azure AI Foundry (Classic deployment).
Auth: Foundry does not yet support Managed Identity for Mistral models; the endpoint
key is stored in Key Vault and retrieved via a Key Vault reference in app settings.
ADI and AI Search use full Managed Identity RBAC.
