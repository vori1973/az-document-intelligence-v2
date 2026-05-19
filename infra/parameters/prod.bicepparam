using '../main.bicep'

param baseName = 'docintv2-prod'
param location = 'eastus2'

param foundryEndpoint = 'https://<foundry-resource>.services.ai.azure.com'
param foundryOcrDeployment = 'mistral-ocr'
param searchIndex = 'document-chunks'
param openaiEmbeddingCapacity = 120
