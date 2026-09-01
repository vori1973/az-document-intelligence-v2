## Why

The APIM exact-cache demo proves baseline versus built-in gateway caching, but it cannot yet show when Azure Managed Redis is the better cache backing store. A follow-on demo path is needed to compare APIM built-in cache and Azure Managed Redis using the same RAG backend, cache identity, generation invalidation, and presenter evidence.

## What Changes

- Add an Azure Managed Redis-backed APIM exact-response cache operation alongside the existing baseline and built-in-cache operations.
- Provision Azure Managed Redis and APIM external-cache configuration through Bicep, including the required connection-string/access-key integration as an explicit platform exception.
- Reuse the existing normalized-question, generation, security-scope, prompt-version, and logical-model cache-key contract for Redis-backed response caching.
- Extend response headers, telemetry dimensions, integration tests, and demo tooling so a presenter can compare baseline, APIM built-in cache, and APIM Redis cache in one run.
- Preserve the same backend implementation and managed-identity query path so observed differences come from cache storage behavior, not RAG logic changes.
- Keep application-managed Redis artifact caching, semantic caching, and a full Azure Monitor workbook outside this change.

## Capabilities

### New Capabilities

- `apim-managed-redis-cache-demo`: Defines the externally observable behavior for APIM exact-response caching backed by Azure Managed Redis and its comparison with built-in APIM caching.

### Modified Capabilities

None.

## Impact

- Extends the hand-written Bicep deployment with Azure Managed Redis, APIM external cache registration, secure named values, outputs, and deployment switches.
- Adds a new APIM operation, policy, and tests for `POST /rag/apim-redis`.
- Updates the presenter driver, documentation, and Azure integration scenarios to demonstrate built-in versus Redis-backed exact caching.
- Introduces a credential-handling exception for APIM-to-Redis because APIM external cache integration requires a Redis connection string; Redis access keys must be generated and stored only as secure APIM configuration.
