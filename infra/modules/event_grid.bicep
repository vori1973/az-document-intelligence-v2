@description('Storage account name (event source)')
param storageAccountName string

@description('Storage account ID')
param storageAccountId string

@description('Location')
param location string = resourceGroup().location

// System topic only — event subscriptions are created post-deploy (after func publish)
// because Event Grid validates the function endpoint exists before creating subscriptions.
resource systemTopic 'Microsoft.EventGrid/systemTopics@2022-06-15' = {
  name: '${storageAccountName}-topic'
  location: location
  properties: {
    source: storageAccountId
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

output systemTopicName string = systemTopic.name
output systemTopicId string = systemTopic.id
