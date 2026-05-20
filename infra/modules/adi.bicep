@description('Azure Document Intelligence resource name')
param adiName string

@description('Location')
param location string = resourceGroup().location

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

output adiEndpoint string = adi.properties.endpoint
output adiId string = adi.id
