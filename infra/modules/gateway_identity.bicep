// =============================================================================
// gateway_identity.bicep — user-assigned managed identity for the API gateway
//
// The APIM instance authenticates to the query Function App with this identity
// (see infra/policies/rag-api.xml, `authentication-managed-identity`).
//
// It is user-assigned rather than system-assigned for one reason: App Service
// Authentication/Authorization on the backend must allow-list the *client* (app)
// ID of the calling identity, and a system-assigned identity's client ID does
// not exist until the parent resource is created. A user-assigned identity
// exposes `properties.clientId` at deployment time, so the backend's allow-list
// can be wired in code instead of a manual portal step (task 4.3).
// =============================================================================

@description('User-assigned managed identity name')
param identityName string

@description('Location')
param location string = resourceGroup().location

resource gatewayIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}

output identityId string = gatewayIdentity.id
output identityName string = gatewayIdentity.name
output principalId string = gatewayIdentity.properties.principalId
output clientId string = gatewayIdentity.properties.clientId
