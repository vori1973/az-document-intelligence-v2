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

@description('Object ID of the deploying user/SP — granted Key Vault Secrets Officer during deploy')
param deployerPrincipalId string = ''

@description('Set to false to disable Mistral OCR — ADI handles all pages')
param ocrEnabled string = 'false'

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

// ── Azure Document Intelligence (deploy before functions to get real endpoint) ──
module adi './modules/adi.bicep' = {
  name: 'adi'
  params: {
    adiName: adiName
    location: location
  }
}

// ── Azure OpenAI (deploy before functions to get real endpoint) ───────────
module openai './modules/openai.bicep' = {
  name: 'openai'
  params: {
    openaiName: openaiName
    location: location
    embeddingCapacity: openaiEmbeddingCapacity
  }
}

// ── Function App (after adi/openai so we can use their real endpoints) ────
module functions './modules/functions.bicep' = {
  name: 'functions'
  params: {
    functionAppName: functionAppName
    planName: planName
    location: location
    storageAccountName: storageAccountName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    keyVaultUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/'
    storageAccountUrl: 'https://${storageAccountName}.blob.${environment().suffixes.storage}'
    adiEndpoint: adi.outputs.adiEndpoint
    foundryEndpoint: foundryEndpoint
    foundryOcrDeployment: foundryOcrDeployment
    aoaiEndpoint: openai.outputs.aoaiEndpoint
    aoaiEmbeddingDeployment: 'text-embedding-ada-002'
    searchEndpoint: 'https://${searchServiceName}.search.windows.net'
    searchIndex: searchIndex
    ocrEnabled: ocrEnabled
  }
}

// ── ADI RBAC (after functions so we have principalId) ─────────────────────
module adiRbac './modules/adi_rbac.bicep' = {
  name: 'adiRbac'
  params: {
    adiName: adiName
    functionAppPrincipalId: functions.outputs.principalId
  }
}

// ── Azure OpenAI RBAC (after functions so we have principalId) ────────────
module openaiRbac './modules/openai_rbac.bicep' = {
  name: 'openaiRbac'
  params: {
    openaiName: openaiName
    functionAppPrincipalId: functions.outputs.principalId
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
    deployerPrincipalId: deployerPrincipalId
  }
}

// ── Event Grid ────────────────────────────────────────────────────────────
module eventgrid './modules/event_grid.bicep' = {
  name: 'eventgrid'
  params: {
    storageAccountName: storageAccountName
    storageAccountId: storage.outputs.storageAccountId
    location: location
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────
output functionAppName string = functionAppName
output systemTopicName string = eventgrid.outputs.systemTopicName
output storageAccountUrl string = storage.outputs.storageAccountUrl
output adiEndpoint string = adi.outputs.adiEndpoint
output aoaiEndpoint string = openai.outputs.aoaiEndpoint
output searchEndpoint string = search.outputs.searchEndpoint
output keyVaultUrl string = keyvault.outputs.keyVaultUrl
output keyVaultName string = keyVaultName
output appInsightsConnectionString string = monitoring.outputs.appInsightsConnectionString
