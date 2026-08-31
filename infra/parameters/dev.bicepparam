using '../main.bicep'

// Base name — all resource names are derived from this
param baseName = 'docintv2-dev'

// Location — pick one where ADI, OpenAI, and AI Search are all available
param location = 'eastus'

// Foundry endpoint — set this AFTER manually creating the Foundry resource
// and deploying the Mistral OCR model (see scripts/deploy.sh step 1)
param foundryEndpoint = 'https://<foundry-resource>.services.ai.azure.com'

// Disable OCR until Foundry/Mistral subscription is resolved
param ocrEnabled = 'false'

// Optional overrides
// param foundryOcrDeployment = 'mistral-ocr'
// param searchIndex = 'document-chunks-dev'
// param openaiEmbeddingCapacity = 60

// ── APIM exact-cache demo (openspec: add-apim-exact-cache-demo) ───────────
// Off by default: turning these on adds a query Function App, its own plan and
// storage, and an APIM instance (Basic v2 is the cheapest tier with a built-in
// cache). Before enabling, create the backend Entra application out of band:
//
//   APP_ID=$(az ad app create --display-name docintv2-dev-query-api \
//              --query appId -o tsv)
//   az ad app update --id "$APP_ID" --identifier-uris "api://$APP_ID"
//   az ad sp create --id "$APP_ID"
//
// then set queryBackendClientId below. Leaving it unset while deployQuery is
// true would publish an unauthenticated backend, so scripts/deploy.sh refuses
// that combination.
//
param deployQuery = true
param deployApim = true
param queryBackendClientId = '8ba44700-ecf7-4d55-a97a-72d6b1485b7a'
param apimPublisherEmail = 'vori1973@users.noreply.github.com'
param apimPublisherName = 'RAG cache demo'
param knowledgeGeneration = '1'
param cacheTtlSeconds = 300
param queryAlwaysReadyInstanceCount = 1
