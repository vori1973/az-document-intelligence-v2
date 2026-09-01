## Context

See `proposal.md` for motivation and `specs/apim-managed-redis-cache-demo/spec.md` for the behavior contract. The current `add-apim-exact-cache-demo` implementation already provides a separate `query/` Function App, APIM `/rag/baseline` and `/rag/apim-built-in` operations, shared cache-key construction in APIM policy and Python tests, generation publication, proof headers, a demo driver, and Azure integration tests.

This change should extend that foundation rather than create another query path. The important new constraint is platform-specific: APIM external cache integration supports Redis-compatible caches, including Azure Managed Redis, through a Redis connection string. Microsoft Entra authentication is not currently available for APIM-to-Azure Managed Redis external cache configuration, so this design must contain a narrow, auditable credential exception while preserving managed identity for Search, Azure OpenAI, backend invocation, and all other service boundaries.

## Goals / Non-Goals

**Goals:**

- Add a Redis-backed APIM exact-response cache operation that is comparable to the existing built-in-cache operation.
- Provision Azure Managed Redis and APIM external-cache registration through Bicep, not portal-only steps.
- Keep the same backend route, request validation, normalization, cache-key dimensions, generation invalidation, and cache eligibility rules.
- Make built-in versus Redis cache behavior visible from presenter output and telemetry.
- Treat Redis lookup/store failures as protected misses or fallbacks.
- Keep Redis credentials secure and out of outputs, logs, telemetry, headers, and docs examples.

**Non-Goals:**

- Application-managed Redis caching inside the query app.
- Semantic caching or vector similarity cache reuse.
- A production multitenant authorization model.
- Replacing APIM exact-response caching with backend response caching.
- A complete Azure Monitor Workbook or browser UI.
- Migrating the existing built-in-cache operation to Redis; both modes remain available for comparison.

## Decisions

### Add a third APIM operation over the existing backend

APIM will expose:

- `POST /rag/baseline` for uncached control traffic.
- `POST /rag/apim-built-in` for internal APIM exact-response cache.
- `POST /rag/apim-redis` for external APIM exact-response cache backed by Azure Managed Redis.

The Redis-backed operation will rewrite to the same backend route as the existing operations and use the same API-scope policy for bounded JSON parsing, trusted headers, normalization, cache-key construction, backend authentication, and proof headers. The operation policy will differ only in cache lookup/store behavior and cache-type labelling.

**Alternative considered:** Add Redis as a replacement for `/rag/apim-built-in`. That would hide the comparison the demo is intended to make and remove the current working built-in-cache proof.

### Use APIM external cache policies for Redis-backed response values

The Redis operation will mirror the built-in custom cache policy and use APIM's `cache-lookup-value` / `cache-store-value` with external caching. The value stored remains the same envelope used by the built-in policy so cache-hit response reconstruction, cached backend invocation metadata, and sensitive-data controls stay consistent.

The operation should prefer explicit external cache semantics. If the policy uses `caching-type="external"`, a missing external cache configuration must fail visibly into fallback behavior rather than silently using built-in cache. If implementation proves APIM error behavior is too disruptive for live demos, `prefer-external` can be considered only with a response header or deployment check that proves which backing store was used.

**Alternative considered:** Implement Redis calls in the query backend. That is application-managed caching, not APIM external response caching, and it would not compare APIM cache backends directly.

### Provision Azure Managed Redis and APIM external cache through Bicep

Add a Redis module and APIM external-cache wiring controlled by deployment parameters:

```text
deployRedis
redisSku
redisCapacity
redisPublicNetworkAccess
redisCacheTtlSeconds or shared cacheTtlSeconds
```

The APIM module will register the Redis instance as an external cache for the APIM service location or default gateway scope, using a secure named value or equivalent ARM resource property for the Redis connection string. Bicep outputs may include Redis resource name and hostname, but not access keys or connection strings.

**Alternative considered:** Document a portal step to add the external cache after deployment. That would make the demo non-reproducible and conflict with the repository rule to avoid hand-editing Azure resources.

### Treat APIM-to-Redis key authentication as a constrained exception

The repository default remains managed identity only. For this one integration, APIM requires a Redis connection string for external cache registration, so the implementation will:

- enable only the Redis access mechanism APIM needs;
- store the connection string as secure APIM configuration;
- never emit it as a deployment output;
- never print it from deployment/demo scripts;
- add tests that scan Bicep/policy/script outputs for accidental exposure; and
- document why this exception exists and where it is contained.

The query backend continues to use managed identity for Azure AI Search and Azure OpenAI. Redis credentials must not be added to query app settings unless a future application-managed cache change explicitly requires it.

**Alternative considered:** Wait for APIM support for Microsoft Entra authentication to Azure Managed Redis. That is cleaner but would block the requested demo path indefinitely.

### Keep cache identity and invalidation identical across cache stores

Redis-backed exact-response caching uses the same logical key dimensions as built-in cache:

```text
normalized question hash + knowledge generation + security scope + prompt version + logical model version
```

The exposed key ID remains opaque and derived from the full cache key. The cache-type dimension is observable metadata, not part of answer identity by default; built-in and Redis stores are already isolated by backing store and operation. If implementation needs a prefix to prevent accidental cross-store collision in shared Redis, use a storage namespace such as `apim:response:` without changing the externally asserted answer identity dimensions.

Generation publication remains the correctness boundary. Bumping the active generation makes old Redis entries unreachable, and TTL handles cleanup.

**Alternative considered:** Add Redis-specific cache dimensions. That would make built-in and Redis results harder to compare because key differences could explain misses.

### Extend the presenter and integration tests

`scripts/demo_apim_cache.py` should support the new operation in the same fixed sequence:

```text
baseline x2
built-in cache x2
Redis cache x2
optional generation bump evidence
```

The output should show cache type, outcome, key ID, backend invocation ID, cached backend invocation ID, elapsed time, citations, and token/dependency metadata. Automated Azure tests should include Redis miss/hit, normalization equivalence, generation-change miss, uncached error behavior, fallback behavior where feasible, direct-backend rejection still unaffected, and telemetry evidence that Redis hits produce no backend work.

**Alternative considered:** Add a separate Redis-only demo script. Keeping one comparison driver prevents presenter drift and makes side-by-side evidence easier.

## Risks / Trade-offs

- **[APIM external cache silently falls back to internal cache]** -> Prefer `caching-type="external"` and add deployment/integration checks that prove Redis-backed operation reports the Redis cache type only when external cache is configured.
- **[Redis credential leaks through outputs or logs]** -> Keep connection material in secure APIM configuration only and add static tests for Bicep outputs, policy files, scripts, and docs snippets.
- **[Access-key authentication conflicts with managed-identity policy]** -> Document this as a constrained APIM platform exception and keep all query dependencies on managed identity.
- **[Redis regional latency narrows the demo benefit]** -> Deploy Redis in the same region as APIM by default and document SKU/network choices for customer environments.
- **[Cache store comparison is polluted by existing entries]** -> Use unique questions in tests and clear presenter expectations that the first call per store should miss unless deliberately primed.
- **[External cache failure amplifies backend traffic]** -> Keep rate limiting immediately after cache lookup and preserve backend timeout/concurrency protection.
- **[Redis cost surprises users]** -> Keep Redis deployment behind an explicit `deployRedis` switch and document SKU/cost implications in the demo guide.

## Migration Plan

1. Add Redis deployment parameters defaulted off so existing deployments remain unchanged.
2. Provision Azure Managed Redis and APIM external-cache registration when `deployRedis` and `deployApim` are enabled.
3. Add the Redis-backed APIM operation and policy while leaving baseline and built-in operations unchanged.
4. Validate Redis miss/hit behavior with a unique question before adding it to presenter documentation.
5. Extend the demo driver and docs to show baseline, built-in cache, and Redis cache side by side.
6. Add integration tests for Redis cache behavior and telemetry, skipped unless Redis deployment variables are supplied.

Rollback disables or removes the Redis-backed operation first, then removes APIM external-cache registration and the Redis resource through Bicep. Existing baseline, built-in-cache, query backend, ingestion pipeline, Search index content, and document artifacts remain unchanged. Redis entries can expire naturally by TTL; no bulk purge is required for correctness.

## Open Questions

- Confirm the lowest acceptable Azure Managed Redis SKU for the target demo region and expected request volume.
- Confirm whether APIM `caching-type="external"` has the desired fallback semantics in the chosen APIM tier, or whether a guarded `prefer-external` policy plus deployment proof is needed for live demo resilience.
