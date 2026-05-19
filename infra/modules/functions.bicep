@description('Function App name')
param functionAppName string

@description('App Service Plan name')
param planName string

@description('Location')
param location string = resourceGroup().location

@description('Storage account name (for AzureWebJobsStorage)')
param storageAccountName string

@description('Application Insights connection string')
param appInsightsConnectionString string

@description('Key Vault URL')
param keyVaultUrl string

@description('Storage account URL')
param storageAccountUrl string

@description('ADI endpoint')
param adiEndpoint string

@description('ADI model')
param adiModel string = 'prebuilt-layout'

@description('Foundry endpoint')
param foundryEndpoint string

@description('Foundry OCR deployment name')
param foundryOcrDeployment string

@description('Azure OpenAI endpoint')
param aoaiEndpoint string

@description('Azure OpenAI embedding deployment')
param aoaiEmbeddingDeployment string = 'text-embedding-ada-002'

@description('Azure AI Search endpoint')
param searchEndpoint string

@description('Azure AI Search index name')
param searchIndex string

resource plan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: planName
  location: location
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  kind: 'functionapp'
  properties: {
    reserved: true  // Linux
  }
}

resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    siteConfig: {
      pythonVersion: '3.11'
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storageAccountName }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'TASK_HUB_NAME', value: 'docpipeline' }
        { name: 'STORAGE_ACCOUNT_URL', value: storageAccountUrl }
        { name: 'DOCUMENTS_CONTAINER', value: 'documents' }
        { name: 'PROCESSING_CONTAINER', value: 'processing' }
        { name: 'ADI_ENDPOINT', value: adiEndpoint }
        { name: 'ADI_MODEL', value: adiModel }
        { name: 'ADI_FETCH_FIGURES', value: 'false' }
        { name: 'FOUNDRY_ENDPOINT', value: foundryEndpoint }
        { name: 'FOUNDRY_OCR_DEPLOYMENT', value: foundryOcrDeployment }
        { name: 'FOUNDRY_KEY_SECRET_NAME', value: 'foundry-key' }
        { name: 'KEY_VAULT_URL', value: keyVaultUrl }
        { name: 'AOAI_ENDPOINT', value: aoaiEndpoint }
        { name: 'AOAI_EMBEDDING_DEPLOYMENT', value: aoaiEmbeddingDeployment }
        { name: 'AZURE_SEARCH_ENDPOINT', value: searchEndpoint }
        { name: 'AZURE_SEARCH_INDEX', value: searchIndex }
        { name: 'OCR_FIGURE_ROUTING', value: 'true' }
        { name: 'OCR_MAX_CONCURRENT_PAGES', value: '5' }
        { name: 'PIPELINE_VERSION', value: 'v2.0' }
      ]
    }
  }
}

output functionAppName string = functionApp.name
output functionAppId string = functionApp.id
output principalId string = functionApp.identity.principalId
output functionAppDefaultHostname string = functionApp.properties.defaultHostName
