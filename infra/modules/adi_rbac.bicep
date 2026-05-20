@description('Name of the existing ADI account')
param adiName string

@description('Function App principal ID')
param functionAppPrincipalId string

resource adi 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: adiName
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
