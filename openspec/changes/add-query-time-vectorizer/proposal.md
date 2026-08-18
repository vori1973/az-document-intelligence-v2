## Why

The search index stores document embeddings but has no server-side vectorizer, so clients such as Azure AI Foundry must generate query embeddings themselves before issuing vector queries. Adding a query-time vectorizer will let supported clients submit plain-text queries directly while reusing the existing Azure OpenAI embedding deployment.

## What Changes

- Add an Azure OpenAI query-time vectorizer to the Azure AI Search index.
- Associate the vectorizer with the index's existing vector search profile and embedding field.
- Configure the search service managed identity to access the existing embedding deployment.
- Preserve the current document embedding pipeline and direct-vector query behavior.

## Capabilities

### New Capabilities
- `query-time-vectorizer`: Allows plain-text vector queries to be embedded by the search index using the existing Azure OpenAI embedding deployment.

### Modified Capabilities
- None.

## Impact

- `infra/modules/search.bicep` and related infrastructure wiring for the search service identity and vector search configuration.
- Azure AI Search index behavior and client integrations that use text-based vector queries.
- No new application runtime dependency; the existing Azure OpenAI embedding deployment remains the model source.
