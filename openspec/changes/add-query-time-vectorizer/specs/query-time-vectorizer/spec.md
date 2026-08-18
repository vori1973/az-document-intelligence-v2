## Purpose

This capability enables clients to submit plain-text vector queries to the search index, which generates query embeddings through the existing Azure OpenAI embedding deployment.

## ADDED Requirements

### Requirement: Query-time vectorization is available on the search index

The search index SHALL define a query-time vectorizer that references the existing Azure OpenAI embedding deployment, and SHALL associate that vectorizer with the vector search profile used by the searchable embedding field.

#### Scenario: Plain-text vector query succeeds

- **WHEN** a client submits a text-based vector query targeting the embedding field
- **THEN** the search service generates the query embedding with the configured Azure OpenAI deployment and executes vector search without the client providing numeric vector values

#### Scenario: Vectorizer uses the existing embedding model

- **WHEN** the index configuration is deployed
- **THEN** the vectorizer references the same embedding deployment and dimensionality used to generate indexed document embeddings

### Requirement: Embedding deployment access uses managed identity

The search service SHALL hold the data-plane authorization required to call the Azure OpenAI embedding deployment, and the configuration SHALL NOT require an API key or stored secret.

#### Scenario: Managed identity authorization is present

- **WHEN** infrastructure is deployed
- **THEN** the search service managed identity can invoke the embedding deployment for query vectorization

#### Scenario: Existing direct-vector queries remain supported

- **WHEN** a client supplies a numeric query vector directly
- **THEN** the search index continues to execute the vector query using the existing vector profile and field
