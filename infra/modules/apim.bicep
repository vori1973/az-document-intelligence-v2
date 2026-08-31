// =============================================================================
// apim.bicep — API Management gateway for the RAG cache demonstration
//              (tasks 5.1 / 5.2 / 5.5 / 5.6 / 5.7 / 6.1)
//
// Exposes two operations over ONE backend so that measured differences come
// from caching alone:
//
//     POST /rag/baseline        — always invokes the query Function App
//     POST /rag/apim-built-in   — exact-response cache over the same backend
//
// Everything the gateway trusts (knowledge generation, security scope, prompt
// version, logical model version, TTL, limits, backend audience) is a named
// value written by this template. Callers cannot influence cache identity, and
// publishing a new knowledge generation is a configuration change here rather
// than a code change (task 6.1).
//
// SKU (task 5.1): Basic v2 is the lowest-cost tier that supports the built-in
// (internal) cache required by cache-lookup-value/cache-store-value. The
// Consumption tier has no internal cache at all, and Developer has no SLA and
// is not licensed for production use. Parameterized so a demonstration can move
// up to Standard v2 without touching policy.
// =============================================================================

@description('API Management service name')
param apimName string

@description('Location')
param location string = resourceGroup().location

@description('APIM SKU. BasicV2 is the lowest-cost tier with a built-in cache; Consumption has none')
@allowed([
  'BasicV2'
  'StandardV2'
  'PremiumV2'
  'Developer'
  'Basic'
  'Standard'
  'Premium'
])
param sku string = 'BasicV2'

@description('APIM scale units')
@minValue(1)
param skuCapacity int = 1

@description('Publisher email shown on APIM notifications')
param publisherEmail string

@description('Publisher name shown on APIM notifications')
param publisherName string

@description('Resource ID of the user-assigned identity APIM uses to authenticate to the query backend')
param gatewayIdentityId string

@description('Client (application) ID of that identity — referenced by the authentication-managed-identity policy')
param gatewayIdentityClientId string

@description('Query Function App base URL, including the /api route prefix')
param queryBackendUrl string

@description('Entra audience APIM requests a token for when calling the query backend (typically api://<backendClientId>)')
param backendAudience string

@description('Application Insights resource ID — reused from the existing monitoring resources')
param appInsightsId string

@description('Application Insights connection string. The only connection string in this deployment; every other dependency uses managed identity')
@secure()
param appInsightsConnectionString string

@description('Log Analytics workspace resource ID — reused from the existing monitoring resources')
param workspaceId string

@description('Require an APIM subscription key on the demo API')
param subscriptionRequired bool = true

// ── Trusted cache dimensions (task 5.4 / 6.1) ─────────────────────────────
@description('Active knowledge generation. Non-secret; publishing a new corpus means changing this value')
param knowledgeGeneration string = '0'

@description('Cache-partition security scope. Demonstrates partitioning for a single controlled corpus — NOT tenant authorization')
param securityScope string = 'demo-public'

@description('Grounded prompt version')
param promptVersion string = 'v1'

@description('Logical model/answer-contract version')
param logicalModelVersion string = 'v1'

// ── Cache and protection knobs (task 5.5 / 5.7) ───────────────────────────
@description('Built-in cache TTL in seconds. Short by design: knowledge generation is the correctness boundary, TTL is only cleanup')
@minValue(1)
param cacheTtlSeconds int = 300

@description('Maximum accepted request body size in bytes')
@minValue(1)
param maxRequestBytes int = 16384

@description('Maximum accepted question length in characters — mirrors QUERY_MAX_QUESTION_LENGTH on the backend')
@minValue(1)
param maxQuestionLength int = 2000

@description('Maximum response size that may be stored in the built-in cache, in bytes')
@minValue(1)
param maxCachedResponseBytes int = 262144

@description('Backend calls allowed per renewal period across the demo operations')
@minValue(1)
param backendRateLimitCalls int = 60

@description('Rate-limit renewal period in seconds (APIM maximum is 300)')
@minValue(1)
@maxValue(300)
param backendRateLimitPeriodSeconds int = 60

@description('Backend forward-request timeout in seconds (APIM maximum is 240)')
@minValue(1)
@maxValue(240)
param backendTimeoutSeconds int = 120

var apiName = 'rag-demo'
var baselineOperationName = 'rag-baseline'
var builtInCacheOperationName = 'rag-apim-built-in'
var backendName = 'rag-query-backend'

// Every value the policies reference with {{...}}. Named values are the only
// deployment-managed input to policy behavior, so a policy file can be reviewed
// on its own and a generation bump is a one-value change.
var ragNamedValues = [
  { name: 'rag-knowledge-generation', value: knowledgeGeneration }
  { name: 'rag-security-scope', value: securityScope }
  { name: 'rag-prompt-version', value: promptVersion }
  { name: 'rag-logical-model-version', value: logicalModelVersion }
  { name: 'rag-cache-ttl-seconds', value: string(cacheTtlSeconds) }
  { name: 'rag-max-request-bytes', value: string(maxRequestBytes) }
  { name: 'rag-max-question-length', value: string(maxQuestionLength) }
  { name: 'rag-max-cached-response-bytes', value: string(maxCachedResponseBytes) }
  { name: 'rag-backend-rate-limit-calls', value: string(backendRateLimitCalls) }
  { name: 'rag-backend-rate-limit-period-seconds', value: string(backendRateLimitPeriodSeconds) }
  { name: 'rag-backend-timeout-seconds', value: string(backendTimeoutSeconds) }
  { name: 'rag-backend-audience', value: backendAudience }
  { name: 'rag-apim-identity-client-id', value: gatewayIdentityClientId }
]

// Only non-sensitive demo headers are logged. No body is configured for any
// diagnostic, so questions, prompts, retrieved text, and cached payloads are
// never captured in telemetry.
var loggedRequestHeaders = [
  'X-Demo-Cache-Mode'
  'X-Demo-Correlation-Id'
  'X-Demo-Generation'
  'X-Demo-Security-Scope'
  'X-Demo-Prompt-Version'
  'X-Demo-Model-Version'
]

var loggedResponseHeaders = [
  'x-demo-cache'
  'x-demo-cache-type'
  'x-demo-cache-eligible'
  'x-demo-cache-key-id'
  'x-demo-cache-store'
  'x-demo-correlation-id'
  'x-demo-generation'
  'x-demo-backend-invocation-id'
  'x-demo-cached-backend-invocation-id'
  'Server-Timing'
]

resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apimName
  location: location
  sku: {
    name: sku
    capacity: skuCapacity
  }
  identity: {
    // System-assigned covers future gateway-to-Azure needs; the user-assigned
    // identity is the one the backend allow-lists, because its client ID is
    // known before APIM exists.
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${gatewayIdentityId}': {}
    }
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    virtualNetworkType: 'None'
  }
}

resource namedValues 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = [for nv in ragNamedValues: {
  parent: apim
  name: nv.name
  properties: {
    displayName: nv.name
    value: nv.value
    secret: false
  }
}]

resource appInsightsConnectionNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'rag-appinsights-connection-string'
  properties: {
    displayName: 'rag-appinsights-connection-string'
    value: appInsightsConnectionString
    secret: true
  }
}

// ── Backend ───────────────────────────────────────────────────────────────
resource queryBackend 'Microsoft.ApiManagement/service/backends@2024-05-01' = {
  parent: apim
  name: backendName
  properties: {
    title: 'RAG query Function App'
    description: 'Managed-identity authenticated backend for both demo cache modes'
    protocol: 'http'
    url: queryBackendUrl
    tls: {
      validateCertificateChain: true
      validateCertificateName: true
    }
  }
}

// ── API ───────────────────────────────────────────────────────────────────
resource ragApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: apiName
  properties: {
    displayName: 'RAG exact-cache demo'
    description: 'Baseline and APIM built-in exact-response cache operations over one RAG query backend'
    path: 'rag'
    protocols: [
      'https'
    ]
    subscriptionRequired: subscriptionRequired
    serviceUrl: queryBackendUrl
  }
}

resource ragApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: ragApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('../policies/rag-api.xml')
  }
  dependsOn: [
    namedValues
    queryBackend
  ]
}

// ── Operations ────────────────────────────────────────────────────────────
// The operation names are part of the policy contract: rag-api.xml derives the
// reported cache type from context.Operation.Id.
resource baselineOperation 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: ragApi
  name: baselineOperationName
  properties: {
    displayName: 'Baseline RAG query (uncached)'
    description: 'Always invokes the query backend'
    method: 'POST'
    urlTemplate: '/baseline'
    request: {
      description: 'JSON body with a bounded question'
      representations: [
        {
          contentType: 'application/json'
        }
      ]
    }
    responses: [
      {
        statusCode: 200
        description: 'Grounded answer, citations, and execution metadata'
        representations: [
          {
            contentType: 'application/json'
          }
        ]
      }
    ]
  }
}

resource baselineOperationPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-05-01' = {
  parent: baselineOperation
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('../policies/rag-baseline.xml')
  }
  dependsOn: [
    ragApiPolicy
  ]
}

resource builtInCacheOperation 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = {
  parent: ragApi
  name: builtInCacheOperationName
  properties: {
    displayName: 'RAG query with APIM built-in exact cache'
    description: 'Exact-response cache lookup and store around the same query backend'
    method: 'POST'
    urlTemplate: '/apim-built-in'
    request: {
      description: 'JSON body with a bounded question'
      representations: [
        {
          contentType: 'application/json'
        }
      ]
    }
    responses: [
      {
        statusCode: 200
        description: 'Grounded answer served from the backend (miss) or the built-in cache (hit)'
        representations: [
          {
            contentType: 'application/json'
          }
        ]
      }
    ]
  }
}

resource builtInCacheOperationPolicy 'Microsoft.ApiManagement/service/apis/operations/policies@2024-05-01' = {
  parent: builtInCacheOperation
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('../policies/rag-apim-built-in.xml')
  }
  dependsOn: [
    ragApiPolicy
  ]
}

// API-scoped subscription so the demo does not need a product, and so the key
// can be read on demand with the CLI instead of being emitted as a template
// output.
resource ragSubscription 'Microsoft.ApiManagement/service/subscriptions@2024-05-01' = if (subscriptionRequired) {
  parent: apim
  name: 'rag-demo'
  properties: {
    displayName: 'RAG exact-cache demo'
    scope: '/apis/${ragApi.name}'
    state: 'active'
    allowTracing: false
  }
}

// ── Diagnostics (task 5.2) ────────────────────────────────────────────────
resource appInsightsLogger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apim
  name: 'rag-appinsights'
  properties: {
    loggerType: 'applicationInsights'
    description: 'Shared Application Insights instance used by the ingestion pipeline'
    resourceId: appInsightsId
    credentials: {
      connectionString: '{{rag-appinsights-connection-string}}'
    }
    isBuffered: true
  }
  dependsOn: [
    appInsightsConnectionNamedValue
  ]
}

resource appInsightsDiagnostic 'Microsoft.ApiManagement/service/diagnostics@2024-05-01' = {
  parent: apim
  name: 'applicationinsights'
  properties: {
    loggerId: appInsightsLogger.id
    alwaysLog: 'allErrors'
    verbosity: 'information'
    logClientIp: false
    httpCorrelationProtocol: 'W3C'
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    frontend: {
      request: {
        headers: loggedRequestHeaders
      }
      response: {
        headers: loggedResponseHeaders
      }
    }
    backend: {
      request: {
        headers: loggedRequestHeaders
      }
      response: {
        headers: loggedResponseHeaders
      }
    }
  }
}

resource azureMonitorLogger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apim
  name: 'azuremonitor'
  properties: {
    loggerType: 'azureMonitor'
    description: 'Gateway logs to the shared Log Analytics workspace'
    isBuffered: true
  }
}

resource azureMonitorDiagnostic 'Microsoft.ApiManagement/service/diagnostics@2024-05-01' = {
  parent: apim
  name: 'azuremonitor'
  properties: {
    loggerId: azureMonitorLogger.id
    alwaysLog: 'allErrors'
    verbosity: 'information'
    logClientIp: false
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    frontend: {
      request: {
        headers: loggedRequestHeaders
      }
      response: {
        headers: loggedResponseHeaders
      }
    }
    backend: {
      request: {
        headers: loggedRequestHeaders
      }
      response: {
        headers: loggedResponseHeaders
      }
    }
  }
}

resource apimToWorkspace 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'rag-apim-to-log-analytics'
  scope: apim
  properties: {
    workspaceId: workspaceId
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output apimName string = apim.name
output apimId string = apim.id
output gatewayUrl string = apim.properties.gatewayUrl
output apimPrincipalId string = apim.identity.principalId
output baselineUrl string = '${apim.properties.gatewayUrl}/rag/baseline'
output builtInCacheUrl string = '${apim.properties.gatewayUrl}/rag/apim-built-in'
output apiName string = apiName
output subscriptionName string = subscriptionRequired ? 'rag-demo' : ''
output knowledgeGenerationNamedValue string = 'rag-knowledge-generation'
