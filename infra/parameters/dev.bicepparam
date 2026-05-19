using '../main.bicep'

// Base name — all resource names are derived from this
param baseName = 'docintv2-dev'

// Location — pick one where ADI, OpenAI, and AI Search are all available
param location = 'eastus2'

// Foundry endpoint — set this AFTER manually creating the Foundry resource
// and deploying the Mistral OCR model (see scripts/deploy.sh step 1)
param foundryEndpoint = 'https://<foundry-resource>.services.ai.azure.com'

// Optional overrides (defaults are fine for dev)
// param foundryOcrDeployment = 'mistral-ocr'
// param searchIndex = 'document-chunks-dev'
// param openaiEmbeddingCapacity = 60
