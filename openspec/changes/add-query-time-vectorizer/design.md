## Context

The existing index definition stores an `embedding` vector field and uses an Azure OpenAI deployment named `text-embedding-ada-002` for document embeddings. The search service currently has no server-side vectorizer, while the search service and OpenAI resources are provisioned through separate Bicep modules. See `proposal.md` for the motivation and `specs/query-time-vectorizer/spec.md` for the observable contract.

## Goals / Non-Goals

**Goals:**

- Add an Azure OpenAI vectorizer to the existing vector search configuration.
- Bind the vectorizer to the existing profile and embedding field.
- Grant the search service managed identity permission to invoke the embedding deployment.
- Keep direct numeric vector queries and the document embedding activity unchanged.

**Non-Goals:**

- Changing the embedding model, embedding dimensions, chunk schema, or document indexing pipeline.
- Adding client-side embedding code or a new application dependency.
- Introducing a second search index or a separate query API.

## Decisions

- **Configure the vectorizer in the existing search index definition.** This keeps query-time embedding beside the vector field/profile it serves and avoids a parallel index configuration.
- **Reference the existing Azure OpenAI deployment by deployment name and endpoint.** Reusing the deployed model prevents query/index embedding incompatibility; introducing a new deployment would add cost and migration risk.
- **Use the search service managed identity for Azure OpenAI access.** This follows the repository's managed-identity-only rule and avoids distributing API keys. The infrastructure must add the corresponding role assignment at the Azure OpenAI account scope.
- **Pass the OpenAI resource details through the existing Bicep module wiring.** This keeps resource ownership explicit and avoids hard-coded environment-specific endpoints.
- **Retain the current vector profile for both query forms.** Text queries will be vectorized by the profile's vectorizer, while numeric vectors continue to use the same field and profile without behavioral changes.

## Risks / Trade-offs

- [Risk] Query-time vectorization adds a dependency on Azure OpenAI availability and latency → Mitigation: reuse the existing deployment and preserve direct-vector query support as a fallback.
- [Risk] Search and Azure OpenAI identity or role-assignment wiring may be incomplete in an existing environment → Mitigation: deploy through Bicep and validate the resulting index configuration and a text-based vector query.
- [Risk] The model deployment and indexed vector dimensions could drift → Mitigation: source both configurations from the existing embedding deployment parameters and verify dimensions before rollout.

## Migration Plan

1. Update the search and identity Bicep modules to define the vectorizer and required role assignment.
2. Deploy the infrastructure so the index configuration and authorization are updated.
3. Validate a plain-text vector query and an existing numeric-vector query.
4. Roll back by removing the vectorizer and role assignment from Bicep and redeploying; direct-vector search remains the compatibility path.
