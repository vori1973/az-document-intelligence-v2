using '../main.bicep'

param baseName = 'docintv2-prod'
param location = 'eastus2'

param adiEndpoint = 'https://<adi-resource>.cognitiveservices.azure.com/'
param foundryEndpoint = 'https://<foundry-resource>.services.ai.azure.com'
param foundryOcrDeployment = 'mistral-ocr'
param aoaiEndpoint = 'https://<openai-resource>.openai.azure.com/'
param searchIndex = 'document-chunks'
