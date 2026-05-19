# Requirements: v2 Pipeline

## Functional

1. Uploading a PDF to `documents/` container triggers the full ingestion pipeline automatically
2. Deleting a PDF removes all associated AI Search chunks and processing artifacts
3. Re-uploading a changed PDF (same name, different content) removes old chunks and indexes new ones
4. Re-uploading the same PDF (same content hash) is a no-op (idempotent)
5. Each pipeline step's output artifact is stored in Blob Storage for auditability and retry
6. OCR fan-out processes pages in parallel with configurable concurrency limit
7. All 7 pipeline steps (pre-analysis → ADI → router → OCR → chunks → embed → search) execute in order
8. Stale chunk cleanup runs before re-indexing on document update

## Non-functional

1. All authentication via Entra / DefaultAzureCredential — no API keys in code or non-KV settings
2. Retry with exponential backoff on transient failures (3 retries, via Durable Functions retry policy)
3. Structured telemetry to Application Insights for every step (start, end, error, custom metrics)
4. IaC in Bicep — `az deployment sub create` deploys all resources in one command
5. Local development works with `az login` + Azure Functions Core Tools

## Entra Authentication Requirements

- ADI client: `DocumentAnalysisClient(endpoint, DefaultAzureCredential())`
- Blob client: `BlobServiceClient(account_url, DefaultAzureCredential())`
- Search client: `SearchClient(endpoint, index, DefaultAzureCredential())`
- OpenAI client: `AzureOpenAI(azure_endpoint, azure_ad_token_provider=...)`
- Foundry/Mistral OCR: Key Vault secret (Foundry Classic does not support MI for Mistral)
  — endpoint key retrieved once at cold start from Key Vault using MI
- Key Vault access: `SecretClient(vault_url, DefaultAzureCredential())`
