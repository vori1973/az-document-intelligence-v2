targetScope = 'resourceGroup'

@description('Base name used to derive all resource names')
param baseName string

@description('Location')
param location string = resourceGroup().location

@description('Azure AI Foundry endpoint (created manually — Mistral requires marketplace terms)')
param foundryEndpoint string

@description('Foundry OCR deployment name')
param foundryOcrDeployment string = 'mistral-ocr'

@description('Azure AI Search index name')
param searchIndex string = 'document-chunks'

@description('Azure OpenAI embedding deployment capacity (TPM / 1000)')
param openaiEmbeddingCapacity int = 120

@description('Set to false to disable Mistral OCR — ADI handles all pages')
param ocrEnabled string = 'true'

// ── Resource names ────────────────────────────────────────────────────────
var storageAccountName = '${take(replace(baseName, '-', ''), 18)}st'
var functionAppName    = '${baseName}-func'
var planName           = '${baseName}-plan'
var searchServiceName  = '${baseName}-search'
var keyVaultName       = '${take(baseName, 20)}-kv'
var workspaceName      = '${baseName}-logs'
var appInsightsName    = '${baseName}-ai'
var adiName            = '${baseName}-adi'
var openaiName         = '${baseName}-oai'

// ── Monitoring (deployed first — other modules need connection string) ────
module monitoring './modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    workspaceName: workspaceName
    appInsightsName: appInsightsName
    location: location
  }
}

// ── ADI (provisioned by Bicep, Entra auth via RBAC) ──────────────────────
// RBAC assigned after Function App MI is known — deploy functions first
// (ADI module depends on principalId so it comes after the functions module)

// ── Function App (deploy before RBAC modules so we get principalId) ───────
module functions './modules/functions.bicep' = {
  name: 'functions'
  params: {
    functionAppName: functionAppName
    planName: planName
    location: location
    storageAccountName: storageAccountName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    keyVaultUrl: 'https://${keyVaultName}.vault.azure.net/'
    storageAccountUrl: 'https://${storageAccountName}.blob.core.windows.net'
    adiEndpoint: 'https://${adiName}.cognitiveservices.azure.com/'
    foundryEndpoint: foundryEndpoint
    foundryOcrDeployment: foundryOcrDeployment
    aoaiEndpoint: 'https://${openaiName}.openai.azure.com/'
    aoaiEmbeddingDeployment: 'text-embedding-ada-002'
    searchEndpoint: 'https://${searchServiceName}.search.windows.net'
    searchIndex: searchIndex
    ocrEnabled: ocrEnabled
  }
}

// ── Azure Document Intelligence ───────────────────────────────────────────
module adi './modules/adi.bicep' = {
  name: 'adi'
  params: {
    adiName: adiName
    location: location
    functionAppPrincipalId: functions.outputs.principalId
  }
}

// ── Azure OpenAI ──────────────────────────────────────────────────────────
module openai './modules/openai.bicep' = {
  name: 'openai'
  params: {
    openaiName: openaiName
    location: location
    functionAppPrincipalId: functions.outputs.principalId
    embeddingCapacity: openaiEmbeddingCapacity
  }
}

// ── Storage ───────────────────────────────────────────────────────────────
module storage './modules/storage.bicep' = {
  name: 'storage'
  params: {
    storageAccountName: storageAccountName
    location: location
    functionAppPrincipalId: functions.outputs.principalId
  }
}

// ── AI Search ─────────────────────────────────────────────────────────────
module search './modules/search.bicep' = {
  name: 'search'
  params: {
    searchServiceName: searchServiceName
    location: location
    functionAppPrincipalId: functions.outputs.principalId
  }
}

// ── Key Vault ─────────────────────────────────────────────────────────────
module keyvault './modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    keyVaultName: keyVaultName
    location: location
    functionAppPrincipalId: functions.outputs.principalId
  }
}

// ── Event Grid ────────────────────────────────────────────────────────────
module eventgrid './modules/event_grid.bicep' = {
  name: 'eventgrid'
  dependsOn: [storage, functions]
  params: {
    storageAccountName: storageAccountName
    storageAccountId: storage.outputs.storageAccountId
    functionAppHostname: functions.outputs.functionAppDefaultHostname
    functionAppName: functionAppName
    location: location
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────
output functionAppName string = functionAppName
output storageAccountUrl string = storage.outputs.storageAccountUrl
output adiEndpoint string = adi.outputs.adiEndpoint
output aoaiEndpoint string = openai.outputs.aoaiEndpoint
output searchEndpoint string = search.outputs.searchEndpoint
output keyVaultUrl string = keyvault.outputs.keyVaultUrl
output keyVaultName string = keyVaultName
output appInsightsConnectionString string = monitoring.outputs.appInsightsConnectionString
