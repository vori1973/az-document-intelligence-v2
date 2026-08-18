## 1. Search Infrastructure Configuration

- [ ] 1.1 Update the search index Bicep definition to add an Azure OpenAI query-time vectorizer referencing the existing embedding endpoint, deployment, model, and vector dimensions.
- [ ] 1.2 Associate the vectorizer with the existing vector search profile used by the `embedding` field while preserving direct numeric vector queries.
- [ ] 1.3 Wire the Azure OpenAI resource endpoint and embedding deployment parameters through the existing Bicep modules without hard-coded environment-specific values.

## 2. Managed Identity Authorization

- [ ] 2.1 Ensure the search service has a system-assigned managed identity available to the index configuration.
- [ ] 2.2 Add the least-privilege Azure OpenAI role assignment required for the search service identity to invoke embeddings, using existing RBAC module patterns.

## 3. Validation and Documentation

- [ ] 3.1 Add or update infrastructure validation coverage for the vectorizer, profile association, deployment reference, and managed-identity authorization.
- [ ] 3.2 Validate a plain-text vector query against the deployed index and confirm an existing numeric-vector query still works.
- [ ] 3.3 Update relevant pipeline or demo documentation to remove the no-vectorizer limitation and show the text-based vector query shape.
