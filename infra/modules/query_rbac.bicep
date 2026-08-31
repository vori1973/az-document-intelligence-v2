// =============================================================================
// query_rbac.bicep — least-privilege data-plane access for the query app (task 4.2)
//
// The online query path only ever reads index documents and calls model
// deployments, so it gets exactly two roles:
//
//   Search Index Data Reader     — query the index; cannot write or delete
//                                  documents and cannot change index schema
//                                  (contrast with the ingestion app, which
//                                  holds Search Index Data Contributor and
//                                  Search Service Contributor).
//   Cognitive Services OpenAI User — call embedding and chat deployments with
//                                  Entra tokens; cannot manage deployments.
//
// Both services have local auth disabled, so this is the only way in — there is
// no key or connection string to fall back on.
// =============================================================================

@description('Name of the existing Azure AI Search service')
param searchServiceName string

@description('Name of the existing Azure OpenAI account')
param openaiName string

@description('Principal ID of the query Function App system-assigned identity')
param queryFunctionAppPrincipalId string

resource searchService 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: searchServiceName
}

resource openai 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openaiName
}

var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var cognitiveServicesOpenAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource querySearchReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, queryFunctionAppPrincipalId, searchIndexDataReaderRoleId)
  scope: searchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
    principalId: queryFunctionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource queryOpenAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openai.id, queryFunctionAppPrincipalId, cognitiveServicesOpenAiUserRoleId)
  scope: openai
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUserRoleId)
    principalId: queryFunctionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output searchIndexDataReaderRoleId string = searchIndexDataReaderRoleId
output cognitiveServicesOpenAiUserRoleId string = cognitiveServicesOpenAiUserRoleId
