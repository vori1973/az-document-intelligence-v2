@description('Azure Document Intelligence resource name')
param adiName string

@description('Location')
param location string = resourceGroup().location

@description('Function App principal ID for RBAC')
param functionAppPrincipalId string

@description('SKU — S0 is the standard paid tier')
param sku string = 'S0'

resource adi 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: adiName
  location: location
  kind: 'FormRecognizer'
  sku: { name: sku }
  properties: {
    publicNetworkAccess: 'Enabled'
    networkAcls: { defaultAction: 'Allow' }
  }
}

// Cognitive Services User — allows DefaultAzureCredential to call ADI
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource adiRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(adi.id, functionAppPrincipalId, cognitiveServicesUserRoleId)
  scope: adi
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: functionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output adiEndpoint string = adi.properties.endpoint
output adiId string = adi.id
