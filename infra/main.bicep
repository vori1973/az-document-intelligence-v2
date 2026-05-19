targetScope = 'resourceGroup'

@description('Base name used to derive all resource names')
param baseName string

@description('Location')
param location string = resourceGroup().location

@description('ADI endpoint')
param adiEndpoint string

@description('Azure AI Foundry endpoint')
param foundryEndpoint string

@description('Foundry OCR deployment name')
param foundryOcrDeployment string

@description('Azure OpenAI endpoint')
param aoaiEndpoint string

@description('Azure AI Search index name')
param searchIndex string = 'document-chunks'

// ── Resource names ────────────────────────────────────────────────────────
var storageAccountName = '${take(replace(baseName, '-', ''), 18)}st'
var functionAppName    = '${baseName}-func'
var planName           = '${baseName}-plan'
var searchServiceName  = '${baseName}-search'
var keyVaultName       = '${take(baseName, 20)}-kv'
var workspaceName      = '${baseName}-logs'
var appInsightsName    = '${baseName}-ai'

// ── Monitoring (deployed first — other modules need connection string) ────
module monitoring './modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    workspaceName: workspaceName
    appInsightsName: appInsightsName
    location: location
  }
}

// ── Function App (deploy before storage/search so we get the principalId) ─
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
    adiEndpoint: adiEndpoint
    foundryEndpoint: foundryEndpoint
    foundryOcrDeployment: foundryOcrDeployment
    aoaiEndpoint: aoaiEndpoint
    searchEndpoint: 'https://${searchServiceName}.search.windows.net'
    searchIndex: searchIndex
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
output searchEndpoint string = search.outputs.searchEndpoint
output keyVaultUrl string = keyvault.outputs.keyVaultUrl
output appInsightsConnectionString string = monitoring.outputs.appInsightsConnectionString
