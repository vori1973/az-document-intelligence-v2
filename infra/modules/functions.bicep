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

@description('Set to false to disable Mistral OCR — ADI handles all pages (use when Foundry subscription unavailable)')
param ocrEnabled string = 'true'

@description('Set to false to skip vision-based figure understanding — figure chunks fall back to caption-only text')
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

resource plan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: planName
  location: location
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  kind: 'functionapp'
  properties: {
    reserved: true  // Linux
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storageAccountUrl}/deployments'
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 100
        instanceMemoryMB: 2048
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
        { name: 'AzureWebJobsStorage__accountName', value: storageAccountName }
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
        { name: 'OCR_ENABLED', value: ocrEnabled }
        { name: 'OCR_FIGURE_ROUTING', value: 'true' }
        { name: 'OCR_MAX_CONCURRENT_PAGES', value: '5' }
        { name: 'FIGURE_UNDERSTANDING_ENABLED', value: figureUnderstandingEnabled }
        { name: 'FIGURE_UNDERSTANDING_MODEL', value: figureUnderstandingModel }
        { name: 'FIGURE_MODEL_PREMIUM', value: figureModelPremium }
        { name: 'FIGURE_MODEL_ECONOMY', value: figureModelEconomy }
        { name: 'FIGURE_PREMIUM_MAX_FIGURES', value: string(figurePremiumMaxFigures) }
        { name: 'FIGURE_CROP_DPI', value: '200' }
        { name: 'FIGURE_MAX_CONCURRENT', value: '4' }
        { name: 'FIGURE_PER_PAGE_ALLOWANCE', value: string(figurePerPageAllowance) }
        { name: 'FIGURE_MAX_PER_DOC_CEILING', value: string(figureMaxPerDocCeiling) }
        { name: 'PIPELINE_VERSION', value: 'v2.0' }
      ]
    }
  }
}

output functionAppName string = functionApp.name
output functionAppId string = functionApp.id
output principalId string = functionApp.identity.principalId
output functionAppDefaultHostname string = functionApp.properties.defaultHostName
