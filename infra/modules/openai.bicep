@description('Azure OpenAI resource name')
param openaiName string

@description('Location — must support Azure OpenAI')
param location string = resourceGroup().location

@description('Embedding model deployment name')
param embeddingDeploymentName string = 'text-embedding-ada-002'

@description('Embedding model capacity (TPM / 1000)')
param embeddingCapacity int = 120

@description('Vision model deployment name')
param figureModelDeploymentName string = 'gpt-4o-mini'

@description('Vision model deployment capacity (TPM / 1000)')
param figureModelCapacity int = 250

resource openai 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: openaiName
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    networkAcls: { defaultAction: 'Allow' }
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openai
  name: embeddingDeploymentName
  sku: {
    name: 'Standard'
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-ada-002'
      version: '2'
    }
  }
}

resource figureModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openai
  name: figureModelDeploymentName
  dependsOn: [
    embeddingDeployment
  ]
  sku: {
    name: 'GlobalStandard'
    capacity: figureModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
      version: '2024-07-18'
    }
  }
}

output aoaiEndpoint string = openai.properties.endpoint
output embeddingDeploymentName string = embeddingDeployment.name
output figureModelDeploymentName string = figureModelDeployment.name
output openaiId string = openai.id
