## Context

See `proposal.md` for motivation and `specs/apim-exact-cache-demo/spec.md` for the behavior contract. The repository currently has an ingestion-focused Python Durable Functions app, a Search index populated with embedded chunks, Azure OpenAI deployments, and working query logic in `scripts/demo.py`. It also has hand-written Bicep modules and existing Application Insights and Log Analytics resources, but repository guidance records that application telemetry is not currently flowing.

The initial proof must isolate caching effects from query implementation differences, preserve the proven client-side query-embedding path while `add-query-time-vectorizer` remains incomplete, and avoid claiming tenant isolation that the current index cannot enforce.

## Goals / Non-Goals

**Goals:**

- Deploy a small query service independently from ingestion scaling and lifecycle.
- Route baseline and exact-cache operations to one backend implementation.
- Make cache hits, dependency avoidance, token avoidance, and generation invalidation directly demonstrable.
- Keep cache identity stable, privacy-preserving, and extensible to later Redis-backed modes.
- Use managed identity and repository-managed infrastructure throughout.
- Establish reliable correlated telemetry before relying on measurements.

**Non-Goals:**

- Azure Managed Redis, application-managed caches, or semantic caching.
- Streaming answer responses.
- A production multitenant authorization model or Search security trimming.
- Replacing explicit query embedding with a Search vectorizer.
- A complete customer-facing workbook or browser application.
- Automatic generation publication from the ingestion orchestrator in the first proof.

## Decisions

### Deploy a separate Python Function App for online queries

Add a second, non-Durable Python Function App for the query API rather than adding an HTTP query route to the ingestion app. It will have independent scaling, deployment, identity, and availability settings while sharing the existing Search and Azure OpenAI resources.

The query code will live in a dedicated application directory with pure modules for request validation, cache identity, retrieval, answer generation, response construction, and telemetry. Reusable logic will be extracted from `scripts/demo.py`; the script will call or import the shared query logic rather than remain a competing implementation.

**Alternative considered:** Add the endpoint to `src/function_app.py`. This reduces resources but couples user-facing query traffic to Event Grid and Durable Functions workloads and grants the query path the ingestion app's broader identity.

### Keep APIM operations as policy variants over one backend

APIM will expose:

- `POST /rag/baseline`, which always forwards to the backend.
- `POST /rag/apim-built-in`, which performs custom cache lookup and storage around the same backend.

Both operations will rewrite to the same backend route and set trusted internal headers for cache mode, active generation, fixed demo security scope, prompt version, logical model version, and correlation ID. APIM will remove or overwrite caller-provided internal headers.

**Alternative considered:** Separate backend routes or deployments per cache mode. That makes demonstrations harder to interpret because code or configuration drift can explain measured differences.

### Use custom key/value policies for POST exact caching

The built-in-cache operation will parse a bounded JSON body, normalize the question using a documented algorithm (Unicode-preserving lowercase, trim, and collapse whitespace), hash the normalized value with SHA-256, and construct a namespaced key from trusted dimensions:

```text
rag-response:v1:
  scope:{securityScope}:
  generation:{knowledgeGeneration}:
  prompt:{promptVersion}:
  model:{logicalModelVersion}:
  query:{normalizedQuestionHash}
```

APIM will use custom cache lookup/store policies because the operation is POST and the key must include request-body and version dimensions. Only a short hash-derived key ID will be exposed. The API will implement the same normalization helper and tests so contract drift is detected, while APIM remains authoritative for response-cache lookup.

**Alternative considered:** Convert the operation to GET or use basic response-cache policy defaults. Questions do not fit safely or consistently in query strings, and implicit URL-based identity omits required answer dimensions.

### Publish generation through trusted APIM configuration

The first implementation will store the active generation as an APIM named value managed by Bicep/deployment configuration. A documented publish command or script will update it only after ingestion and queryability checks succeed. Old cache entries will expire by TTL but cannot be reached by requests using the new generation.

The client request may display a generation for demonstration convenience, but it cannot choose the cache partition. APIM injects the active value and the backend reports it.

**Alternative considered:** Read generation from every request or purge cache after ingestion. Caller control is unsafe, while bulk purges are slower, operationally fragile, and difficult to scope.

### Cache only validated success responses

APIM will store only non-streaming, eligible 2xx JSON responses from the built-in-cache operation. Validation errors, backend errors, timeouts, filtered responses, and non-query routes will bypass storage. A cache lookup/store error will be recorded and treated as a miss; normal APIM backend rate limiting and timeout policies remain active to prevent a cache incident from amplifying load.

The initial TTL will be configurable and intentionally short enough for demonstrations. Generation remains the correctness boundary; TTL is cleanup and risk reduction.

**Alternative considered:** Cache all backend responses to maximize hit rate. This can preserve transient failures and makes recovery behavior misleading.

### Separate per-request proof from aggregate telemetry

APIM will set response headers for cache outcome, cache type, active generation, opaque key ID, and correlation ID. Backend misses will include an invocation ID plus dependency-called flags, durations, token counts, and `Server-Timing`. A cache hit may return the cached backend payload, including the original invocation metadata, while APIM's hit header and current request correlation ID remain authoritative for the current request.

Structured telemetry will use stable dimensions rather than raw content. APIM diagnostics and query-service telemetry will target the existing Log Analytics workspace. Implementation starts by repairing and proving telemetry flow, then adds cache and dependency events.

**Alternative considered:** Prove caching only with logs or elapsed time. That is fragile during a live demonstration and does not prove that Search, model calls, and tokens were avoided.

### Authenticate each service boundary independently

The query Function App's system-assigned identity will receive Search Index Data Reader and Cognitive Services OpenAI User roles only. APIM's managed identity will authenticate to the backend protected by App Service Authentication/Authorization with an audience dedicated to the query API. Public access to the backend remains technically reachable only as an authenticated endpoint; clients use APIM.

The initial `securityScope` is a trusted fixed value such as `demo-public`. It demonstrates cache partitioning but is not authorization because the current Search schema and filters do not enforce tenant scope.

**Alternative considered:** Function keys or service credentials in APIM and application settings. This conflicts with the repository's managed-identity policy and creates secret rotation work.

### Extend the existing Bicep composition

Add modules for query compute, APIM/API policies, and query-specific RBAC/diagnostics, wired from `infra/main.bicep`. Deployment parameters will control whether APIM/query resources are deployed, cache TTL, generation, SKUs, and existing Search/OpenAI reuse. No portal-only configuration is part of the supported path.

The query app will use a separate hosting plan by default so ingestion load does not consume query capacity. Development SKUs and limits remain parameterized.

**Alternative considered:** Manual proof-of-concept resources. They are quick to create but cannot be reproduced, reviewed, or safely rolled back.

## Risks / Trade-offs

- **[APIM policy normalization differs from Python normalization]** → Define one explicit normalization contract, add shared test vectors, and validate APIM-computed key IDs against backend/test tooling.
- **[Application Insights remains unavailable]** → Make telemetry repair and a synthetic end-to-end trace a deployment gate before cache performance validation.
- **[A cached payload contains original backend execution metadata]** → Treat APIM's per-request cache header and correlation ID as authoritative; label backend metadata as the producing invocation.
- **[Cache failure increases backend traffic]** → Apply backend rate limits, concurrency limits, and timeouts after lookup; emit fallback telemetry and alert on sustained failures.
- **[Shared model deployment creates noisy measurements]** → Avoid concurrent ingestion/load tests and allow a separate logical or physical query model deployment through configuration.
- **[Public networking weakens production relevance]** → Keep networking parameterized and document private endpoint/DNS requirements as a follow-on hardening path.
- **[Manual generation publication is omitted after corpus changes]** → Provide a guarded publish script/runbook and make the active generation visible in every response.
- **[APIM availability or cost complicates local development]** → Keep query-domain logic independently testable and provide direct authenticated backend integration tests; exact gateway behavior is validated in Azure.

## Migration Plan

1. Repair and verify telemetry from a minimal query service into the existing monitoring resources.
2. Deploy the query Function App and least-privilege Search/OpenAI role assignments without changing ingestion resources.
3. Validate direct authenticated backend behavior, grounded citations, dependency metadata, and rejection of unauthenticated access.
4. Deploy APIM, its managed identity, backend authentication, diagnostics, baseline operation, and conservative limits.
5. Add the built-in-cache policy with caching disabled or a unique test namespace, then validate normalization and eligibility behavior.
6. Enable the cache operation, run miss/hit/baseline/generation-change scenarios, and retain evidence from headers and telemetry.
7. Document generation publication and demonstration commands.

Rollback disables or removes APIM query routes first, then removes the query app and its role assignments through Bicep. The existing ingestion pipeline, Search index content, and document artifacts are not migrated or modified, and generation-partitioned cache entries can expire naturally.

## Open Questions

- Select the lowest-cost APIM SKU that supports the required custom cache policies and managed-identity backend authentication in the target development region.
- Confirm whether the existing hosting plan can provide sufficiently isolated query measurements; otherwise retain the default separate plan.
