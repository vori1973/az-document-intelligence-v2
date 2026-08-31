## Why

The repository can ingest and index rich PDF content, but it does not expose a reusable online RAG endpoint or a measurable way to demonstrate the latency and token savings from exact response caching. A small, observable APIM caching proof is needed before adding external Redis or semantic caching complexity.

## What Changes

- Add a separately deployed HTTP RAG Query API that reuses the existing embedding, hybrid retrieval, grounded-answer, and citation behavior.
- Expose baseline and APIM built-in exact-cache operations backed by the same query implementation.
- Define an opaque cache-key contract that partitions responses by normalized question, knowledge generation, security scope, prompt version, and logical model version.
- Add explicit knowledge-generation invalidation so newly published corpus content makes prior cache entries unreachable without a bulk purge.
- Return and record cache, backend invocation, dependency timing, and token metadata that visibly distinguishes misses from gateway hits.
- Add infrastructure, managed-identity RBAC, tests, and a repeatable validation flow for baseline, hit, miss, and generation-change behavior.
- Keep Azure Managed Redis, application-managed caching, semantic caching, and a full workbook/demo package outside this initial change.

## Capabilities

### New Capabilities

- `apim-exact-cache-demo`: Defines the externally observable RAG query, exact-cache, invalidation, response metadata, failure, and telemetry behavior for the initial APIM demonstration.

### Modified Capabilities

None.

## Impact

- Adds a query application and HTTP API separate from the ingestion-focused Durable Functions app.
- Extends the hand-written Bicep deployment with query compute, APIM configuration, diagnostics, and least-privilege role assignments.
- Reuses Azure AI Search, Azure OpenAI, Application Insights, Log Analytics, and retrieval/answer logic currently demonstrated by `scripts/demo.py`.
- Introduces APIM policies and configuration for POST request caching and knowledge-generation publication.
- Requires query-path unit/integration tests and Azure validation of cache behavior, correlation, dependency calls, and token usage.
