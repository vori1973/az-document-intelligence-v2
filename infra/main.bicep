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

@description('Set to false to skip vision-based figure understanding')
param figureUnderstandingEnabled string = 'true'

@description('Vision-capable model deployment used to describe figures')
param figureUnderstandingModel string = 'gpt-4o-mini'

@description('Vision model deployment used for documents at or below the premium figure threshold')
param figureModelPremium string = figureUnderstandingModel

@description('Vision model deployment used for documents above the premium figure threshold')
param figureModelEconomy string = figureUnderstandingModel

@description('Maximum analyzed figures that use the premium vision model')
param figurePremiumMaxFigures int = 60

@description('Qualified figures allowed per document page')
param figurePerPageAllowance int = 4

@description('Absolute maximum figures analyzed per document')
param figureMaxPerDocCeiling int = 500

@description('Set to true to enable the PDF-placement cross-check that recovers figures the document reader missed')
param figureRecoveryEnabled string = 'false'

@description('Overlap fraction above which an embedded image placement is treated as already detected by the document reader')
param figureRecoveryOverlapThreshold string = '0.30'

@description('Image coverage ratio above which a page is treated as scanned and skipped by the recovery cross-check')
param figureScannedPageCoverageThreshold string = '0.85'

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
    figureUnderstandingEnabled: figureUnderstandingEnabled
    figureUnderstandingModel: figureUnderstandingModel
    figureModelPremium: figureModelPremium
    figureModelEconomy: figureModelEconomy
    figurePremiumMaxFigures: figurePremiumMaxFigures
    figurePerPageAllowance: figurePerPageAllowance
    figureMaxPerDocCeiling: figureMaxPerDocCeiling
    figureRecoveryEnabled: figureRecoveryEnabled
    figureRecoveryOverlapThreshold: figureRecoveryOverlapThreshold
    figureScannedPageCoverageThreshold: figureScannedPageCoverageThreshold
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
