@description('Storage account name (event source)')
param storageAccountName string

@description('Storage account ID')
param storageAccountId string

@description('Function App default hostname')
param functionAppHostname string

@description('Function App name')
param functionAppName string

@description('Location')
param location string = resourceGroup().location

resource systemTopic 'Microsoft.EventGrid/systemTopics@2022-06-15' = {
  name: '${storageAccountName}-topic'
  location: location
  properties: {
    source: storageAccountId
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

resource ingestSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2022-06-15' = {
  parent: systemTopic
  name: 'ingest-pdf'
  properties: {
    destination: {
      endpointType: 'AzureFunction'
      properties: {
        resourceId: resourceId('Microsoft.Web/sites/functions', functionAppName, 'ingest_trigger')
        maxEventsPerBatch: 1
        preferredBatchSizeInKilobytes: 64
      }
    }
    filter: {
      includedEventTypes: ['Microsoft.Storage.BlobCreated']
      advancedFilters: [
        {
          operatorType: 'StringEndsWith'
          key: 'subject'
          values: ['.pdf']
        }
        {
          operatorType: 'StringBeginsWith'
          key: 'subject'
          values: ['/blobServices/default/containers/documents/']
        }
      ]
    }
    eventDeliverySchema: 'EventGridSchema'
    retryPolicy: {
      maxDeliveryAttempts: 30
      eventTimeToLiveInMinutes: 1440
    }
  }
}

resource deleteSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2022-06-15' = {
  parent: systemTopic
  name: 'delete-pdf'
  properties: {
    destination: {
      endpointType: 'AzureFunction'
      properties: {
        resourceId: resourceId('Microsoft.Web/sites/functions', functionAppName, 'delete_trigger')
        maxEventsPerBatch: 1
        preferredBatchSizeInKilobytes: 64
      }
    }
    filter: {
      includedEventTypes: ['Microsoft.Storage.BlobDeleted']
      advancedFilters: [
        {
          operatorType: 'StringEndsWith'
          key: 'subject'
          values: ['.pdf']
        }
        {
          operatorType: 'StringBeginsWith'
          key: 'subject'
          values: ['/blobServices/default/containers/documents/']
        }
      ]
    }
    eventDeliverySchema: 'EventGridSchema'
  }
}

output systemTopicId string = systemTopic.id
