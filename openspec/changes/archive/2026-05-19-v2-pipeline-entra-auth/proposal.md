# Proposal: az-document-intelligence-v2 — Azure-Native Pipeline with Entra Authentication

## What

Rewrite the document intelligence pipeline (originally TypeScript, local execution, API keys) as a
production-grade Azure-hosted system using:

- **Python** Azure Durable Functions (serverless, auto-scale)
- **Entra authentication** throughout — `DefaultAzureCredential` + Managed Identity; no API keys in code
- **Azure Blob Storage** event triggers (BlobCreated / BlobDeleted via Event Grid)
- **Azure Bicep** IaC for all resources

## Why

- v1 requires local execution and stores credentials in `.env` files
- v1 has no delete/update handling, no stale-chunk cleanup
- v1 cannot scale — sequential OCR, no retry on transient failures
- Entra (DefaultAzureCredential) eliminates secret management; Managed Identity gives RBAC-scoped access with no rotation needed

## What changes

| Area | v1 | v2 |
|---|---|---|
| Language | TypeScript | Python 3.11 |
| Runtime | `npm run dev` (local) | Azure Durable Functions |
| Trigger | Manual CLI arg | Event Grid (BlobCreated / BlobDeleted) |
| Auth | API keys in `.env` | DefaultAzureCredential (Entra / Managed Identity) |
| OCR parallelism | Sequential pages | Fan-out: parallel extract_page + ocr_page activities |
| Delete/update | Not implemented | Full stale-chunk cleanup |
| Artifacts | Local `output/` | Blob Storage `processing/{doc_id}/{run_id}/` |
| IaC | None | Bicep modules for all resources |

## Success criteria

1. Upload a PDF to Blob Storage → chunks appear in Azure AI Search automatically
2. Delete the PDF → all chunks removed automatically
3. Re-upload a changed PDF → old chunks removed, new chunks indexed
4. No API keys in code, settings, or Key Vault secrets that could be replaced by RBAC
5. All Azure SDK calls authenticated via `DefaultAzureCredential`
