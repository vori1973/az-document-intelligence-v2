// =============================================================================
// query_functions.bicep — the online RAG query Function App (task 4.1 / 4.3)
//
// A second, non-Durable Python Function App, deliberately separate from the
// ingestion app in `infra/modules/functions.bicep`: independent scaling,
// deployment, identity, and availability
// (openspec/changes/add-apim-exact-cache-demo/design.md, "Deploy a separate
// Python Function App for online queries"). Code lives in `query/`.
//
// It also gets its own storage account. The Functions host needs data-plane
// access to whatever account backs it, and pointing the query identity at the
// ingestion account would hand the online query path read/write access to every
// ingested document and processing artifact.
//
// No keys and no connection strings are configured other than the Application
// Insights connection string: Search and Azure OpenAI are reached with this
// app's system-assigned managed identity (see query/rag/auth.py) and host
// storage uses identity-based access.
// =============================================================================

@description('Query Function App name')
param queryFunctionAppName string

@description('Query App Service (Flex Consumption) plan name')
param queryPlanName string

@description('Storage account name backing the query Function App host + deployment container')
param queryStorageAccountName string

@description('Location')
param location string = resourceGroup().location

@description('Application Insights connection string — reused from the existing monitoring resources')
@secure()
param appInsightsConnectionString string

@description('Azure AI Search endpoint')
param searchEndpoint string

@description('Azure AI Search index name')
param searchIndex string

@description('Azure AI Search REST API version used by the query path')
param searchApiVersion string = '2024-07-01'

@description('Azure OpenAI endpoint')
param aoaiEndpoint string

@description('Azure OpenAI chat deployment used for grounded answers')
param chatDeployment string = 'gpt-4o-mini'

@description('Azure OpenAI embedding deployment used for query embeddings')
param embeddingDeployment string = 'text-embedding-ada-002'

@description('Azure OpenAI API version')
param aoaiApiVersion string = '2024-10-21'

@description('Default hybrid-retrieval result count')
param defaultTopK int = 8

@description('Maximum accepted question length in characters')
param maxQuestionLength int = 2000

@description('Active knowledge generation reported when APIM does not supply one')
param knowledgeGeneration string = '0'

@description('Cache-partition security scope reported when APIM does not supply one')
param securityScope string = 'demo-public'

@description('Grounded prompt version reported when APIM does not supply one')
param promptVersion string = 'v1'

@description('Logical model version reported when APIM does not supply one')
param logicalModelVersion string = 'v1'

// ── Capacity (task 4.1: configurable capacity limits) ─────────────────────
@description('Maximum on-demand instances for the query app — kept well below the ingestion app so query load cannot exhaust regional quota')
@minValue(1)
@maxValue(1000)
param maximumInstanceCount int = 40

@description('Per-instance memory in MB')
@allowed([512, 2048, 4096])
param instanceMemoryMB int = 2048

@description('Concurrent HTTP executions per instance')
@minValue(1)
param httpPerInstanceConcurrency int = 8

@description('Always-ready HTTP instances. 0 is cheapest; 1 removes cold start from latency demonstrations')
@minValue(0)
param alwaysReadyInstanceCount int = 0

// ── App Service Authentication/Authorization (task 4.3) ───────────────────
@description('Enable App Service Authentication so only approved Entra identities can invoke the backend')
param authEnabled bool = false

@description('Client ID of the pre-created Entra application that represents this backend API. Created out of band (az ad app create); never provisioned by this template')
param backendClientId string = ''

@description('Accepted token audiences. Defaults to api://<backendClientId> and the raw client ID when empty')
param allowedAudiences array = []

@description('Client (application) IDs allowed to call the backend — the APIM gateway identity plus any approved deployment/test principals')
param allowedClientIds array = []

@description('Expected token issuer. APIM acquires its backend token from the managed-identity endpoint, which returns a v1 token issued by https://sts.windows.net/<tenant>/ — not the v2 login.microsoftonline.com issuer. Override for sovereign clouds')
param authIssuer string = 'https://sts.windows.net/${subscription().tenantId}/'

var resolvedAudiences = empty(allowedAudiences) ? [
  'api://${backendClientId}'
  backendClientId
] : allowedAudiences

var alwaysReady = alwaysReadyInstanceCount > 0 ? [
  {
    name: 'http'
    instanceCount: alwaysReadyInstanceCount
  }
] : []

// ── Dedicated host storage ────────────────────────────────────────────────
resource queryStorage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: queryStorageAccountName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    // Same rationale as the ingestion storage account: Flex Consumption code
    // deployment uploads the package over the public endpoint. Shared keys are
    // disabled, so access is Entra + RBAC only.
    publicNetworkAccess: 'Enabled'
  }
}

resource queryBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: queryStorage
  name: 'default'
}

resource queryDeploymentsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: queryBlobService
  name: 'deployments'
  properties: {
    publicAccess: 'None'
  }
}

// ── Separate hosting plan (query load never competes with ingestion) ──────
resource queryPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: queryPlanName
  location: location
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  kind: 'functionapp'
  properties: {
    reserved: true // Linux
  }
}

resource queryFunctionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: queryFunctionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: queryPlan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${queryStorage.properties.primaryEndpoints.blob}deployments'
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: maximumInstanceCount
        instanceMemoryMB: instanceMemoryMB
        alwaysReady: alwaysReady
        triggers: {
          http: {
            perInstanceConcurrency: httpPerInstanceConcurrency
          }
        }
      }
      runtime: {
        name: 'python'
        version: '3.13'
      }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: queryStorage.name }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'PYTHON_APPLICATIONINSIGHTS_ENABLE_TELEMETRY', value: 'true' }
        { name: 'OTEL_SERVICE_NAME', value: queryFunctionAppName }
        { name: 'AZURE_SEARCH_ENDPOINT', value: searchEndpoint }
        { name: 'AZURE_SEARCH_INDEX', value: searchIndex }
        { name: 'AZURE_SEARCH_API_VERSION', value: searchApiVersion }
        { name: 'AOAI_ENDPOINT', value: aoaiEndpoint }
        { name: 'AOAI_CHAT_DEPLOYMENT', value: chatDeployment }
        { name: 'AOAI_EMBEDDING_DEPLOYMENT', value: embeddingDeployment }
        { name: 'AOAI_API_VERSION', value: aoaiApiVersion }
        { name: 'QUERY_DEFAULT_TOP_K', value: string(defaultTopK) }
        { name: 'QUERY_MAX_QUESTION_LENGTH', value: string(maxQuestionLength) }
        { name: 'QUERY_DEFAULT_GENERATION', value: knowledgeGeneration }
        { name: 'QUERY_DEFAULT_SECURITY_SCOPE', value: securityScope }
        { name: 'QUERY_DEFAULT_PROMPT_VERSION', value: promptVersion }
        { name: 'QUERY_DEFAULT_MODEL_VERSION', value: logicalModelVersion }
      ]
    }
  }
  dependsOn: [
    queryDeploymentsContainer
  ]
}

// ── App Service Authentication/Authorization ──────────────────────────────
// Only tokens issued for `backendClientId` and presented by an allow-listed
// application (the APIM gateway identity, plus any approved deployment/test
// principals) reach the function host; everything else gets 401 without the
// request ever reaching Python (spec: "Direct backend access attempt").
resource queryAuthSettings 'Microsoft.Web/sites/config@2023-12-01' = if (authEnabled) {
  parent: queryFunctionApp
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
    globalValidation: {
      requireAuthentication: true
      // An API backend must reject, never redirect to an interactive login.
      unauthenticatedClientAction: 'Return401'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: authIssuer
          clientId: backendClientId
        }
        validation: {
          allowedAudiences: resolvedAudiences
          defaultAuthorizationPolicy: {
            allowedApplications: allowedClientIds
          }
        }
      }
    }
    login: {
      // Nothing here is an interactive sign-in, so no session store is needed.
      tokenStore: {
        enabled: false
      }
    }
  }
}

// ── Host storage data-plane access for this app's own identity only ───────
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'

resource queryStorageBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(queryStorage.id, queryFunctionApp.id, storageBlobDataContributorRoleId)
  scope: queryStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: queryFunctionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource queryStorageQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(queryStorage.id, queryFunctionApp.id, storageQueueDataContributorRoleId)
  scope: queryStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageQueueDataContributorRoleId)
    principalId: queryFunctionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output queryFunctionAppName string = queryFunctionApp.name
output queryFunctionAppId string = queryFunctionApp.id
output principalId string = queryFunctionApp.identity.principalId
output defaultHostName string = queryFunctionApp.properties.defaultHostName
output queryBackendUrl string = 'https://${queryFunctionApp.properties.defaultHostName}/api'
output authEnabled bool = authEnabled
output queryStorageAccountName string = queryStorage.name
