# APIM Exact-Cache Demo — Deployment, Operations, and Presenter Guide

This is the concrete, current-implementation reference for
`add-apim-exact-cache-demo` (tasks 7.1 / 7.2). For the broader multi-phase
roadmap (external Redis, application caching, semantic caching) see
`docs/APIM-CACHING-EXTENSIBILITY.md`; for the behavior contract see
`openspec/changes/add-apim-exact-cache-demo/specs/apim-exact-cache-demo/spec.md`.

Nothing in this document has been deployed by writing it — deploying,
registering the Entra application, and running the commands below are
separate, explicit operator actions.

---

## 1. Deployment parameters

The demo is off by default. Enabling it means setting these `infra/main.bicep`
parameters (see the commented block in `infra/parameters/dev.bicepparam`):

| Parameter | Default | Purpose |
|---|---|---|
| `deployQuery` | `false` | Deploys the query Function App, its plan/storage, and the gateway identity. |
| `deployApim` | `false` | Deploys APIM and its operations. Requires `deployQuery = true`. |
| `queryChatDeployment` | `gpt-4o-mini` | Azure OpenAI chat deployment the query backend calls. |
| `queryDefaultTopK` | `8` | Default hybrid-retrieval result count. |
| `queryMaxQuestionLength` | `2000` | Enforced identically by APIM and the backend. |
| `queryMaximumInstanceCount` | `40` | Query app scale ceiling — kept below the ingestion app so query load cannot exhaust regional quota. |
| `queryInstanceMemoryMB` | `2048` | Per-instance memory (Flex Consumption: 512/2048/4096). |
| `queryHttpPerInstanceConcurrency` | `8` | Concurrent HTTP executions per instance. |
| `queryAlwaysReadyInstanceCount` | `0` | Set to `1` to remove cold start from a live demo. |
| `queryBackendClientId` | `''` | Client ID of the one-time Entra backend registration (§2). Required when `deployQuery = true`; the deployment fails closed without it. |
| `queryBackendAllowedAudiences` | `[]` | Token audiences the backend accepts. Defaults to `api://<queryBackendClientId>` and the raw client ID. |
| `queryBackendAdditionalAllowedClientIds` | `[]` | Extra approved client IDs (e.g. a test principal) beyond the gateway identity, which is always added automatically. |
| `apimSku` | `BasicV2` | Lowest-cost tier with the built-in cache the demo needs (Consumption has none). |
| `apimSkuCapacity` | `1` | APIM scale units. |
| `apimPublisherEmail` / `apimPublisherName` | `''` / `RAG cache demo` | Required APIM service metadata. |
| `apimSubscriptionRequired` | `true` | Requires an APIM subscription key on the demo API. |
| `knowledgeGeneration` | `'0'` | Active knowledge generation — see §4/§5. |
| `securityScope` | `'demo-public'` | Cache partitioning only — see §6. |
| `promptVersion` / `logicalModelVersion` | `'v1'` / `'v1'` | Additional trusted cache dimensions. |
| `cacheTtlSeconds` | `300` | Built-in cache TTL — see §4. |
| `apimMaxRequestBytes` | `16384` | Gateway request-body ceiling. |
| `apimMaxCachedResponseBytes` | `262144` | Largest response APIM may store. |
| `apimBackendRateLimitCalls` / `apimBackendRateLimitPeriodSeconds` | `60` / `60` | Backend protection shared by both operations. |
| `apimBackendTimeoutSeconds` | `120` | Backend forward-request timeout. |

Deploy with `./scripts/deploy.sh <env>` as usual; it refuses to proceed if
`deployQuery = true` while `queryBackendClientId` is unset (see §2 for why).

---

## 2. One-time Entra backend registration

The query backend is protected by App Service Authentication/Authorization
scoped to a dedicated Entra application — this registration is **not**
provisioned by Bicep (an app registration is a tenant-level object outside
resource-group-scoped IaC) and only needs to happen once per environment. The
service principal is required so Entra can issue managed-identity tokens for
the backend audience:

```bash
APP_ID=$(az ad app create --display-name docintv2-dev-query-api --query appId -o tsv)
az ad app update --id "$APP_ID" --identifier-uris "api://$APP_ID"
az ad sp create --id "$APP_ID"
```

Then record `$APP_ID` in the environment's `.bicepparam` file:

```bicep
param queryBackendClientId = '<APP_ID>'
```

Nothing else references this application: the gateway identity (§3) is
allow-listed automatically because its client ID is available at deployment
time, and any additional approved principal (e.g. a CI test identity) is
added through `queryBackendAdditionalAllowedClientIds`.

---

## 3. Identities and roles

| Identity | Type | Roles / trust |
|---|---|---|
| Query Function App | System-assigned managed identity | **Search Index Data Reader** on Azure AI Search; **Cognitive Services OpenAI User** on Azure OpenAI (`infra/modules/query_rbac.bicep`). No key or connection string for either dependency. |
| Gateway identity (`<baseName>-gw-id`) | User-assigned managed identity | Used by APIM's `authentication-managed-identity` policy to obtain a token for the backend's Entra application audience (`infra/policies/rag-api.xml`). Its client ID is added to the backend's allow-list automatically. |
| APIM service | System + user-assigned managed identity | The user-assigned identity above is attached for backend auth; the system-assigned identity is reserved for future Azure-resource access. |
| Query backend App Service Auth | Entra ID (v1 issuer `https://sts.windows.net/<tenant>/`) | Rejects any caller whose token audience or application ID is not in the allow-list — this is what makes direct, unauthenticated backend access fail (spec: "Direct backend access attempt"). |

No service in this deployment uses a key, a connection string, or a shared
secret for cross-service authentication — the only stored secret is the
Application Insights connection string, referenced as `@secure()` and used
solely for the diagnostics logger.

---

## 4. Cache-key dimensions and TTL

Every cached response's identity is:

```text
rag-response:v1:scope:{securityScope}:generation:{knowledgeGeneration}:
  prompt:{promptVersion}:model:{logicalModelVersion}:query:{sha256(normalized question)}
```

- **Normalization**: trim → collapse internal whitespace to single spaces →
  Unicode-preserving lowercase (`query/rag/normalize.py`, mirrored in
  `infra/policies/rag-api.xml`).
- All four non-question dimensions are **trusted, gateway-controlled values**
  (APIM named values) — a caller cannot influence its own cache partition.
- Only the first 16 hex characters of `sha256(cache key)` — the "key ID" — are
  ever exposed, in the `x-demo-cache-key-id` header.
- **TTL** (`cacheTtlSeconds`, default 300s) is a cleanup/risk-reduction
  mechanism, **not** the correctness boundary — `knowledgeGeneration` is. A
  cache entry from a stale generation is unreachable immediately upon
  publication, regardless of TTL.

---

## 5. Generation publication

Bumping `knowledgeGeneration` is the only supported way to invalidate cache
entries after a corpus change, and it must happen only after the new content
is actually indexed and queryable — publishing early risks caching answers
against a partially-updated index. `scripts/publish_generation.sh` enforces
this order automatically:

```bash
./scripts/publish_generation.sh \
  --resource-group   docintv2-dev-rg \
  --apim-name        docintv2-dev-apim \
  --storage-account  docintv2devst \
  --doc-id           <content-derived doc id of the new/changed document> \
  --run-id           <run id of the ingestion run that processed it> \
  --probe-question   "What does the warranty cover?" \
  --probe-expect     "warranty" \
  --gateway-url      https://docintv2-dev-apim.azure-api.net \
  --new-generation   1
```

It only updates the `rag-knowledge-generation` named value after:

1. confirming `processing/<docId>/<runId>/step7-result.json` exists (the
   pipeline's own completion signal — see `openspec/specs/step-result-files/`
   and `AGENTS.md`), and, optionally, that a supplied Durable Functions
   orchestration instance ID reports `RuntimeStatus=Completed`; and
2. sending a live probe question through `POST /rag/baseline` (the uncached
   control arm, never the cache) and confirming HTTP 200 with the expected
   substring in the answer or a citation.

Either check failing exits non-zero and changes nothing (fail closed) — there
is no override flag. Run with `--dry-run` to validate both checks without
publishing. See `--help` for the full flag list, including
`--no-subscription-key` for deployments with `apimSubscriptionRequired = false`.

Authentication is entirely through the caller's own `az login` session
(interactive user or a pipeline's managed identity); the script defaults to
nothing and stores nothing — the APIM subscription key used for the probe is
read once via the APIM `listSecrets` ARM action and never printed or persisted.

---

## 6. Controlled single-scope limitation

`securityScope` (default `demo-public`) demonstrates that the cache key
*can* be partitioned by an authorization-like dimension — it is **not**
tenant security trimming. The current Azure AI Search index and retrieval
filters contain no enforceable per-tenant field, so every request against a
given deployment retrieves from the same corpus regardless of the scope
value APIM injects. Do not present a caller-visible `securityScope` as
evidence of multitenant isolation; the spec's "Initial scope presentation"
requirement exists precisely to prevent that claim.

---

## 7. Presenter sequence and expected evidence

Drive the sequence with `scripts/demo_apim_cache.py`, which performs exactly
this flow and prints elapsed time, cache/proof headers, citations, and
backend/cached invocation metadata for every call (never the subscription
key):

```bash
.venv/bin/python scripts/demo_apim_cache.py \
  --gateway-url https://docintv2-dev-apim.azure-api.net \
  --resource-group docintv2-dev-rg --apim-name docintv2-dev-apim \
  "What does the warranty cover?"
```

### Act 1 — baseline, twice

`POST /rag/baseline` is called twice with the same question.

Expected evidence:
- both calls return HTTP 200 with `x-demo-cache: BYPASS`;
- **different** `x-demo-backend-invocation-id` values — every call reaches
  the backend, Azure AI Search, and Azure OpenAI again;
- similar (not shrinking) elapsed time and `Server-Timing` on both calls.

### Act 2 — built-in cache: first miss, repeated hit

`POST /rag/apim-built-in` is called twice with the same question.

Expected evidence:
- call 1: `x-demo-cache: MISS`, a fresh `x-demo-backend-invocation-id`, and
  `x-demo-cache-store: stored`;
- call 2 (within `cacheTtlSeconds`): `x-demo-cache: HIT`, **no**
  `x-demo-backend-invocation-id` header (no new backend call), an
  `x-demo-cached-backend-invocation-id` equal to call 1's invocation ID, and
  materially lower elapsed time;
- the same `x-demo-cache-key-id` on both calls.

### Act 3 — generation change: safe invalidation

After publishing a new generation (§5) for the same question:

Expected evidence:
- the repeated question is now `x-demo-cache: MISS` again, with a fresh
  `x-demo-backend-invocation-id` and the new `x-demo-generation` value;
- the answer reflects the newly published corpus;
- no bulk cache purge was performed — the prior generation's entries simply
  became unreachable and continue to expire by TTL.

### Automated evidence

`tests/integration/test_apim_exact_cache.py` encodes Acts 1–3 (plus
normalization equivalence, a second trusted-dimension change, uncached-error
handling, direct-backend rejection, and best-effort telemetry correlation) as
pytest scenarios. They are skipped unless explicitly enabled — see the
environment variables documented in `tests/integration/conftest.py` — because
they require a real deployed gateway and, for two scenarios, extra opt-in to
temporarily mutate a shared APIM named value.

```bash
RAG_INTEGRATION_TESTS=1 \
RAG_APIM_GATEWAY_URL=https://docintv2-dev-apim.azure-api.net \
RAG_APIM_SUBSCRIPTION_KEY=... \
.venv/bin/python -m pytest tests/integration -v
```

### Known limitations of this evidence

- The generation-change and other-trusted-dimension integration scenarios
  mutate a shared APIM named value for the duration of one test and restore
  it in a `finally` block; running them against a demo environment that is
  being presented concurrently will visibly (if briefly) affect other
  traffic's cache identity.
- The telemetry-evidence scenario polls Application Insights for up to two
  minutes because ingestion is eventually consistent; a presenter should not
  rely on it for real-time evidence during a live demo — use the response
  headers above instead.
- `securityScope` partitioning is demonstrable but not enforceable (§6).

---

## 8. Telemetry deployment proof

Both Python Function Apps initialize `azure-monitor-opentelemetry` when
`APPLICATIONINSIGHTS_CONNECTION_STRING` is present. Their Bicep modules also
set `PYTHON_APPLICATIONINSIGHTS_ENABLE_TELEMETRY=true` and distinct
`OTEL_SERVICE_NAME` values. APIM diagnostics send non-sensitive request and
response headers to the same workspace without capturing bodies.

After a successful baseline request, copy its `x-demo-correlation-id` and run:

```bash
az monitor app-insights query \
  --apps docintv2-dev-ai \
  --resource-group docintv2-dev-rg \
  --analytics-query "traces
    | where timestamp > ago(15m)
    | where tostring(customDimensions.correlation_id) == '<correlation-id>'
    | project timestamp, message,
        backendInvocationId=tostring(customDimensions.backend_invocation_id),
        dependency=tostring(customDimensions.dependency),
        searchDurationMs=todouble(customDimensions.search_duration_ms),
        modelDurationMs=todouble(customDimensions.model_duration_ms),
        inputTokens=toint(customDimensions.input_tokens),
        outputTokens=toint(customDimensions.output_tokens)
    | order by timestamp asc" \
  --output table
```

The result must contain `rag.query.start` and `rag.query.success` (or a
correlated `rag.query.error`) and must not contain the question, prompt,
retrieved text, response body, credentials, or direct user identifiers. No
matching row is a deployment failure: check Function App settings, exporter
startup logs, Application Insights ingestion access, and organization policy
assignments before using telemetry as demo evidence.
