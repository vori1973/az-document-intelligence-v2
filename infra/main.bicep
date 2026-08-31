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

// ── Query API / APIM exact-cache demo (openspec: add-apim-exact-cache-demo) ──
// Both switches default to false so existing ingestion deployments are
// unchanged until the demo is explicitly turned on.

@description('Deploy the separate online RAG query Function App, its plan, storage, identity, and least-privilege role assignments')
param deployQuery bool = false

@description('Deploy the API Management gateway with the baseline and built-in exact-cache operations. Requires deployQuery')
param deployApim bool = false

@description('Azure OpenAI chat deployment used for grounded query answers')
param queryChatDeployment string = 'gpt-4o-mini'

@description('Maximum on-demand instances for the query Function App')
param queryMaximumInstanceCount int = 40

@description('Per-instance memory in MB for the query Function App')
@allowed([512, 2048, 4096])
param queryInstanceMemoryMB int = 2048

@description('Concurrent HTTP executions per query Function App instance')
param queryHttpPerInstanceConcurrency int = 8

@description('Always-ready query instances. 0 is cheapest; 1 removes cold start from latency demonstrations')
param queryAlwaysReadyInstanceCount int = 0

@description('Maximum accepted question length in characters, enforced by both APIM and the query backend')
param queryMaxQuestionLength int = 2000

@description('Default hybrid-retrieval result count')
param queryDefaultTopK int = 8

@description('Client ID of the pre-created Entra application representing the query backend. Create it out of band, e.g. az ad app create --display-name <name> --identifier-uris api://<id>')
param queryBackendClientId string = ''

@description('Token audiences accepted by the query backend. Defaults to api://<queryBackendClientId> and the raw client ID')
param queryBackendAllowedAudiences array = []

@description('Additional approved client (application) IDs allowed to call the query backend directly — deployment or test principals. The APIM gateway identity is added automatically')
param queryBackendAdditionalAllowedClientIds array = []

@description('APIM SKU. BasicV2 is the lowest-cost tier that supports the built-in cache the demo requires')
@allowed([
  'BasicV2'
  'StandardV2'
  'PremiumV2'
  'Developer'
  'Basic'
  'Standard'
  'Premium'
])
param apimSku string = 'BasicV2'

@description('APIM scale units')
param apimSkuCapacity int = 1

@description('Publisher email for the APIM instance')
param apimPublisherEmail string = ''

@description('Publisher name for the APIM instance')
param apimPublisherName string = 'RAG cache demo'

@description('Require an APIM subscription key on the demo API')
param apimSubscriptionRequired bool = true

@description('Active knowledge generation used in every cache identity. Publish a new value only after ingestion completes and the corpus is queryable')
param knowledgeGeneration string = '0'

@description('Cache-partition security scope. Demonstrates partitioning for one controlled corpus — not tenant authorization')
param securityScope string = 'demo-public'

@description('Grounded prompt version dimension')
param promptVersion string = 'v1'

@description('Logical model/answer-contract version dimension')
param logicalModelVersion string = 'v1'

@description('Built-in cache TTL in seconds')
param cacheTtlSeconds int = 300

@description('Maximum accepted request body size in bytes at the gateway')
param apimMaxRequestBytes int = 16384

@description('Maximum response size APIM may store in its built-in cache, in bytes')
param apimMaxCachedResponseBytes int = 262144

@description('Backend calls allowed per renewal period across the demo operations')
param apimBackendRateLimitCalls int = 60

@description('Rate-limit renewal period in seconds')
param apimBackendRateLimitPeriodSeconds int = 60

@description('Backend forward-request timeout in seconds')
param apimBackendTimeoutSeconds int = 120


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

// Query / APIM demo resource names
var queryFunctionAppName    = '${baseName}-query-func'
var queryPlanName           = '${baseName}-query-plan'
var queryStorageAccountName = '${take(replace(baseName, '-', ''), 15)}qst'
var gatewayIdentityName     = '${baseName}-gw-id'
var apimServiceName         = '${baseName}-apim'

// Auth is only wired when a backend Entra application has been supplied; the
// registration itself is created out of band, never by this template.
var queryAuthConfigured = !empty(queryBackendClientId)
// Fail closed for direct ARM/Bicep deployments: an incomplete opt-in deploys
// no public query surface. scripts/deploy.sh emits a clear error before ARM.
var queryDeploymentEnabled = deployQuery && queryAuthConfigured
var apimDeploymentEnabled = queryDeploymentEnabled && deployApim && !empty(apimPublisherEmail) && !empty(apimPublisherName)
var queryBackendAudience = empty(queryBackendClientId) ? '' : 'api://${queryBackendClientId}'
var queryAllowedClientIds = union(
  queryDeploymentEnabled ? [gatewayIdentity!.outputs.clientId] : [],
  queryBackendAdditionalAllowedClientIds
)


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

// ═════════════════════════════════════════════════════════════════════════
//  Online RAG query + APIM exact-cache demo (openspec: add-apim-exact-cache-demo)
// ═════════════════════════════════════════════════════════════════════════

// Gateway identity first: the query backend's authentication allow-list needs
// its client ID, and APIM needs the identity to exist before it can be assigned.
module gatewayIdentity './modules/gateway_identity.bicep' = if (queryDeploymentEnabled) {
  name: 'gatewayIdentity'
  params: {
    identityName: gatewayIdentityName
    location: location
  }
}

module queryFunctions './modules/query_functions.bicep' = if (queryDeploymentEnabled) {
  name: 'queryFunctions'
  params: {
    queryFunctionAppName: queryFunctionAppName
    queryPlanName: queryPlanName
    queryStorageAccountName: queryStorageAccountName
    location: location
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    searchEndpoint: search.outputs.searchEndpoint
    searchIndex: searchIndex
    aoaiEndpoint: openai.outputs.aoaiEndpoint
    chatDeployment: queryChatDeployment
    embeddingDeployment: 'text-embedding-ada-002'
    defaultTopK: queryDefaultTopK
    maxQuestionLength: queryMaxQuestionLength
    knowledgeGeneration: knowledgeGeneration
    securityScope: securityScope
    promptVersion: promptVersion
    logicalModelVersion: logicalModelVersion
    maximumInstanceCount: queryMaximumInstanceCount
    instanceMemoryMB: queryInstanceMemoryMB
    httpPerInstanceConcurrency: queryHttpPerInstanceConcurrency
    alwaysReadyInstanceCount: queryAlwaysReadyInstanceCount
    authEnabled: true
    backendClientId: queryBackendClientId
    allowedAudiences: queryBackendAllowedAudiences
    allowedClientIds: queryAllowedClientIds
  }
}

module queryRbac './modules/query_rbac.bicep' = if (queryDeploymentEnabled) {
  name: 'queryRbac'
  params: {
    searchServiceName: searchServiceName
    openaiName: openaiName
    queryFunctionAppPrincipalId: queryFunctions!.outputs.principalId
  }
}

module apim './modules/apim.bicep' = if (apimDeploymentEnabled) {
  name: 'apim'
  params: {
    apimName: apimServiceName
    location: location
    sku: apimSku
    skuCapacity: apimSkuCapacity
    publisherEmail: apimPublisherEmail
    publisherName: apimPublisherName
    gatewayIdentityId: gatewayIdentity!.outputs.identityId
    gatewayIdentityClientId: gatewayIdentity!.outputs.clientId
    queryBackendUrl: queryFunctions!.outputs.queryBackendUrl
    backendAudience: queryBackendAudience
    appInsightsId: monitoring.outputs.appInsightsId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    workspaceId: monitoring.outputs.workspaceId
    subscriptionRequired: apimSubscriptionRequired
    knowledgeGeneration: knowledgeGeneration
    securityScope: securityScope
    promptVersion: promptVersion
    logicalModelVersion: logicalModelVersion
    cacheTtlSeconds: cacheTtlSeconds
    maxRequestBytes: apimMaxRequestBytes
    maxQuestionLength: queryMaxQuestionLength
    maxCachedResponseBytes: apimMaxCachedResponseBytes
    backendRateLimitCalls: apimBackendRateLimitCalls
    backendRateLimitPeriodSeconds: apimBackendRateLimitPeriodSeconds
    backendTimeoutSeconds: apimBackendTimeoutSeconds
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

// Query / APIM demo outputs. Empty strings when the switches are off, so the
// deployment script can branch on presence without failing.
output queryFunctionAppName string = queryDeploymentEnabled ? queryFunctions!.outputs.queryFunctionAppName : ''
output queryBackendUrl string = queryDeploymentEnabled ? queryFunctions!.outputs.queryBackendUrl : ''
output queryBackendAuthEnabled bool = queryDeploymentEnabled ? queryFunctions!.outputs.authEnabled : false
output queryBackendAudience string = queryBackendAudience
output gatewayIdentityClientId string = queryDeploymentEnabled ? gatewayIdentity!.outputs.clientId : ''
output apimName string = apimDeploymentEnabled ? apim!.outputs.apimName : ''
output apimGatewayUrl string = apimDeploymentEnabled ? apim!.outputs.gatewayUrl : ''
output ragBaselineUrl string = apimDeploymentEnabled ? apim!.outputs.baselineUrl : ''
output ragBuiltInCacheUrl string = apimDeploymentEnabled ? apim!.outputs.builtInCacheUrl : ''
output apimSubscriptionName string = apimDeploymentEnabled ? apim!.outputs.subscriptionName : ''
output knowledgeGenerationNamedValue string = apimDeploymentEnabled ? apim!.outputs.knowledgeGenerationNamedValue : ''
output activeKnowledgeGeneration string = knowledgeGeneration
