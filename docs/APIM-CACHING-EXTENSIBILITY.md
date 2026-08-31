# APIM and Redis Caching Extensibility Plan

## Purpose

Extend the existing document-intelligence pipeline into a reusable demonstration
of:

- uncached RAG execution;
- APIM built-in exact-response caching;
- APIM external caching with Azure Managed Redis;
- optional application-managed Redis caching of retrieval artifacts;
- version-based invalidation after document changes; and
- customer-visible latency, dependency, token, and cache telemetry.

The extension should reuse the existing ingestion and indexing pipeline rather
than reproduce a customer-specific AKS environment. The resulting demo should
be portable across customers whose application hosting, network topology, or
model routing differs but whose caching decisions are conceptually the same.

This document is an architectural plan. Implementing the new capability requires
an OpenSpec change before code or infrastructure is modified.

The active implementation contract for the initial exact-caching proof is
`openspec/changes/add-apim-exact-cache-demo/`, tracked by GitHub issue #11.
If this roadmap differs from an approved OpenSpec artifact, the OpenSpec
artifact is authoritative.

---

## Executive recommendation

Keep the existing pipeline responsible for turning PDFs into grounded,
searchable content. Add a separate, thin HTTP query application that performs
the existing retrieval and answer-generation flow. Put APIM in front of that
application and expose multiple operations that differ only in cache policy.

```text
INGESTION — EXISTING
--------------------
PDF -> Blob Storage -> Event Grid -> Durable Functions
    -> Document Intelligence -> chunking -> embeddings
    -> Azure AI Search

ONLINE QUERY — NEW
------------------
Demo UI or load script
          |
          v
         APIM
   +------+-------+----------------+
   |              |                |
baseline    built-in cache    external Redis cache
   |              |                |
   +--------------+----------------+
                  |
                  v
          RAG Query API
                  |
                  +--> existing Azure AI Search
                  +--> existing Azure OpenAI
                  +--> application Redis cache (optional)

OBSERVABILITY
-------------
APIM + RAG Query API + Redis
              |
              v
Application Insights / Log Analytics
              |
              v
      Azure Monitor Workbook
```

This preserves a clear ownership model:

```text
The ingestion pipeline owns document processing and index publication.
APIM owns gateway response caching and cache policy.
The query application owns RAG-aware intermediate caching.
The generation publisher owns cache invalidation.
Azure Monitor owns measurement and presentation.
```

---

## Existing assets to reuse

| Existing asset | Reuse decision | Notes |
|---|---|---|
| Blob-triggered PDF ingestion | Reuse unchanged | Provides a simple and visual document-update workflow |
| Durable Functions pipeline | Reuse unchanged | Keeps ingestion independent from online query traffic |
| Document Intelligence processing | Reuse unchanged | Produces structured text, tables, figures, and citations |
| Chunk and embedding generation | Reuse unchanged | Already creates RAG-ready documents |
| Azure AI Search index | Reuse initially | Contains paragraph, table-row, and figure chunks |
| Azure OpenAI embedding deployment | Reuse | The current query client already generates query embeddings |
| Azure OpenAI chat deployment | Reuse for the proof of value | Consider a separate deployment if ingestion and query traffic contend |
| `scripts/demo.py` retrieval logic | Extract and reuse | `_embed`, `_retrieve`, and `_answer` provide a working reference flow |
| Application Insights and Log Analytics | Reuse after telemetry repair | The resources exist, but telemetry flow is a documented current gap |
| Existing demo documents | Reuse | Grounded answers and figure citations make cache savings tangible |

The existing Function App should remain ingestion-focused. Mixing query traffic
with Event Grid triggers and Durable activities would couple independent
scaling, availability, and deployment concerns.

---

## New components

### 1. RAG Query API

Deploy a small HTTP application, preferably as a separate Azure Function App
for the initial implementation.

```http
POST /api/ask
Content-Type: application/json
```

Example request:

```json
{
  "question": "What maintenance interval does the document specify?",
  "knowledgeGeneration": "17",
  "securityScope": "demo-public"
}
```

Example response:

```json
{
  "answer": "The document specifies ... [1]",
  "sources": [
    {
      "sourceFile": "technical-guide.pdf",
      "page": 12,
      "type": "table_row"
    }
  ],
  "execution": {
    "backendInvocationId": "7d9c8cb2-5fb4-4dca-8cf5-275adbdc7f54",
    "searchCalled": true,
    "modelCalled": true,
    "searchDurationMs": 142,
    "modelDurationMs": 1284,
    "inputTokens": 2184,
    "outputTokens": 176
  }
}
```

The API should:

1. Normalize and hash the question.
2. Generate a query embedding.
3. Perform hybrid retrieval against the existing index.
4. Build a grounded prompt with citations.
5. Invoke the chat model.
6. Return the answer, citations, dependency timings, token usage, and an
   invocation identifier.

The API should use managed identity with least-privilege roles:

- Search Index Data Reader on Azure AI Search.
- Cognitive Services OpenAI User on Azure OpenAI.

It should not receive the ingestion Function App's contributor permissions.

### 2. Azure API Management

Expose three operations backed by the same query API:

```text
POST /rag/baseline
POST /rag/apim-built-in
POST /rag/apim-redis
```

| Operation | Cache behavior |
|---|---|
| `/rag/baseline` | Always invokes the query backend |
| `/rag/apim-built-in` | Uses APIM's internal cache |
| `/rag/apim-redis` | Uses Azure Managed Redis as APIM's external cache |

Using one backend ensures that observed differences come from caching rather
than different retrieval or model implementations.

Because the RAG operation uses POST, the design should use APIM custom
key/value caching policies rather than assume that a basic GET response-cache
policy fits the request.

### 3. Azure Managed Redis

Use Azure Managed Redis for two distinct demonstrations:

1. **APIM external response cache:** the same exact-response behavior as the
   built-in cache, with externally managed capacity and lifecycle.
2. **Application cache:** the query API directly caches selected RAG artifacts,
   such as query embeddings or retrieval results.

Keep key namespaces separate:

```text
apim:response:...
apim:semantic:...
rag:embedding:...
rag:retrieval:...
```

Semantic caching is an optional later phase. It requires an embedding backend,
an appropriate Redis search configuration, representative evaluation queries,
and a correctness review.

### 4. Demo console

Provide either a small browser application or a command-line driver with:

- question input;
- cache-mode selection;
- knowledge-generation input;
- security-scope input;
- repeat-request action;
- version-bump action;
- response headers and body;
- elapsed time;
- source citations; and
- backend invocation ID.

The console must not require the presenter to inspect raw telemetry merely to
prove that a request was cached.

### 5. Azure Monitor Workbook

Deploy a workbook that compares all cache modes using the same logical
workload.

Recommended views:

- request count by cache mode and outcome;
- cache hit rate;
- P50, P95, and P99 end-to-end latency;
- backend invocation count;
- Search call count and avoided Search calls;
- model call count and avoided model calls;
- input and output tokens;
- requests by knowledge generation;
- Redis operation latency and errors;
- cache fallback count; and
- estimated gross and net savings.

---

## Cache-key contract

A cache key must represent everything that can materially change the answer.

Recommended logical structure:

```text
rag-response:
  scope:{securityScope}:
  generation:{knowledgeGeneration}:
  prompt:{promptVersion}:
  model:{logicalModelVersion}:
  query:{normalizedQuestionHash}
```

Rules:

- Do not put raw prompts, secrets, user identifiers, or document content in
  cache keys.
- Use a cryptographic hash of the normalized question.
- Partition by authorization scope whenever retrieval can differ by caller.
- Use a logical model or answer-contract version when multiple physical model
  deployments are expected to produce equivalent behavior.
- Apply caching only to selected query operations.
- Do not cache errors, timeouts, filtered responses, ingestion operations, or
  delete operations by default.

For the initial public-corpus demo, `securityScope` demonstrates cache
partitioning only. It must not be presented as full security trimming until the
Search index and retrieval filters contain enforceable tenant or authorization
fields.

---

## Knowledge-generation invalidation

The pipeline's content-derived `doc_id` identifies an individual document
version, but a pre-retrieval response cache cannot know which document IDs will
support an answer. A query may also depend on multiple documents.

Introduce a corpus or collection generation:

```text
knowledgeGeneration = 17
```

Publication sequence:

1. Upload, replace, or delete a PDF.
2. Run the existing ingestion or cleanup workflow.
3. Confirm all affected Search updates completed successfully.
4. Validate that the new corpus is queryable.
5. Publish generation `18`.
6. New requests include generation `18` in their cache key.
7. Entries from generation `17` become unreachable without requiring a cache
   scan or bulk purge.

TTL remains a safety mechanism, not the primary invalidation guarantee.

### Initial implementation

For a controlled demo, store the generation in an APIM named value or
application configuration and update it explicitly after ingestion.

### Generalized implementation

Store the active generation in Azure App Configuration or a small Blob Storage
manifest. Add a publication step that changes the generation only after all
indexing and validation checks succeed.

For larger deployments, support per-collection or per-product generations so a
change to one corpus does not invalidate unrelated cache entries.

---

## Response headers for visible proof

APIM should add:

```http
x-demo-cache: HIT
x-demo-cache-type: apim-built-in
x-demo-generation: 17
x-demo-cache-key-id: 12c73a...
```

The query API should add:

```http
x-demo-backend-invocation-id: 7d9c8cb2...
x-demo-search-called: true
x-demo-model-called: true
x-demo-input-tokens: 2184
x-demo-output-tokens: 176
Server-Timing: search;dur=142, model;dur=1284
```

On a gateway cache hit, the query backend is not invoked. APIM telemetry is
therefore authoritative for cache hits, while query-API telemetry proves which
dependencies ran on misses.

Do not expose sensitive cache-key material or raw prompts in headers or logs.

---

## Telemetry contract

Use the same correlation ID across APIM, the query API, Search dependencies,
model dependencies, and application Redis operations.

Recommended fields:

```text
correlationId
operationName
cacheEligible
cacheMode
cacheOutcome
cacheKeyId
knowledgeGeneration
securityScopeId
promptVersion
logicalModelVersion
backendInvocationId
searchCalled
modelCalled
embeddingCalled
searchDurationMs
modelDurationMs
redisDurationMs
totalDurationMs
inputTokens
outputTokens
totalTokens
resultCount
statusCode
```

Do not log:

- raw questions by default;
- retrieved chunk text;
- complete model prompts;
- cached response bodies;
- secrets or access tokens; or
- direct user or patient identifiers.

The existing repository notes that Application Insights telemetry is currently
not flowing. Repair and validate telemetry before relying on it during a
customer session. APIM diagnostics and query-API telemetry should write to the
same Log Analytics workspace, while preserving dimensions that distinguish
ingestion events from online-query events.

---

## Application-managed Redis demonstration

Add an optional fourth APIM operation:

```text
POST /rag/application-redis
```

The query API can cache retrieval results under a key such as:

```text
rag:retrieval:
  generation:{knowledgeGeneration}:
  scope:{securityScope}:
  query:{normalizedQuestionHash}
```

Expected behavior:

| Work | First call | Repeated call |
|---|---|---|
| Query embedding | Called or cached separately | Optional cache hit |
| Azure AI Search | Called | Skipped on retrieval-cache hit |
| Prompt assembly | Called | Called |
| Model completion | Called | Called |
| New model tokens | Yes | Yes |

This contrasts with an APIM response-cache hit, which can avoid the entire RAG
workflow and all new model tokens.

---

## Optional semantic-caching phase

Semantic caching should not be required for the first proof of value. Add it
only after exact caching is observable and correct.

Suggested demonstration:

1. Ask: `What maintenance interval is specified for the device?`
2. Store the normal grounded response.
3. Ask: `How often does the device require maintenance?`
4. Show semantic reuse when the similarity threshold is satisfied.
5. Change the knowledge generation.
6. Repeat the paraphrased question and show a miss.

Guardrails:

- Enable only for selected low-volatility operations.
- Do not use with streaming responses unless the selected APIM capability
  explicitly supports it.
- Partition by knowledge generation and authorization scope.
- Preserve citations and their content generation in the cached value.
- Evaluate false-positive reuse with representative query pairs.
- Provide a rapid bypass or disable switch.

Semantic similarity is not proof that two questions require the same answer.

---

## Customer demonstration sequence

### Act 1: establish the baseline

Call `/rag/baseline` twice with the same question.

Show:

- similar end-to-end latency on both calls;
- different backend invocation IDs;
- Search called twice;
- model called twice; and
- new tokens on both calls.

### Act 2: APIM built-in cache

Call `/rag/apim-built-in` twice.

Show:

- first call is a miss;
- second call is a hit;
- significantly lower second-call latency;
- no second backend invocation;
- no second Search call;
- no second model call; and
- no new model tokens.

### Act 3: safe invalidation

Change the knowledge generation and repeat the same question.

Show:

- the request is now a miss;
- the backend executes again; and
- the response is grounded in the currently published corpus.

### Act 4: APIM external Redis

Repeat the exact-cache sequence through `/rag/apim-redis`.

Explain that response behavior is intentionally similar. Redis adds an external
storage lifecycle, capacity control, shared-access options, and a foundation for
application and semantic caching.

### Act 5: application Redis

Call `/rag/application-redis` twice.

Show:

- retrieval is skipped on the second call;
- the model still executes;
- tokens are still consumed; and
- latency reduction is smaller than a full response-cache hit.

### Optional Act 6: semantic cache

Use two validated paraphrases, then change the generation to demonstrate both
semantic reuse and safe invalidation.

---

## Infrastructure extension

Proposed Bicep additions:

```text
infra/modules/query-function.bicep
infra/modules/query-rbac.bicep
infra/modules/apim.bicep
infra/modules/redis.bicep
infra/modules/cache-workbook.bicep
```

Proposed application structure:

```text
query-api/
  function_app.py
  rag.py
  cache_keys.py
  telemetry.py
  requirements.txt
```

The final names should be chosen during the OpenSpec design. The new query
application may instead live under `src/` if the approved design intentionally
uses the existing Function App, but separate deployment is the preferred
default.

Recommended infrastructure parameters:

```text
deployApim
deployRedis
enableApplicationCache
enableSemanticCache
cacheTtlSeconds
knowledgeGenerationSource
queryApiMaximumInstanceCount
apimSku
redisSku
useExistingSearch
useExistingOpenAi
```

Do not manually configure these resources in the portal. Add them to Bicep and
deploy them through the repository's existing infrastructure workflow.

---

## Network and identity considerations

The current development Search and Azure OpenAI resources allow public network
access while using managed identity for data-plane authentication. That is
acceptable for a controlled development demonstration but should remain
parameterized.

For customer environments:

- support private endpoints and private DNS;
- place APIM, the query compute, Search, OpenAI, and Redis in compatible network
  paths;
- keep Redis near the APIM gateway and query application;
- use managed identity wherever the target service supports it;
- do not copy credentials into APIM policies or application settings;
- apply least-privilege data-plane roles; and
- document any Redis authentication constraint that prevents the preferred
  managed-identity pattern.

APIM should authenticate to the query API independently of client
authentication. The query API must treat caller-supplied generation and
security headers as untrusted unless APIM replaces or signs them.

---

## Known constraints and decisions

### No query-time vectorizer yet

The current query client generates the query vector before calling Search. An
active OpenSpec change proposes adding a server-side vectorizer, but it is not
yet implemented.

The first query API should preserve the proven explicit-embedding path. A
server-side vectorizer can be adopted independently after its change is
implemented and validated.

### Index lacks enforceable tenant security fields

The current index supports document and chunk filtering but does not define a
complete tenant, user-group, or authorization contract. The initial cache demo
must use a public or single-scope corpus.

Multitenant use requires:

- enforceable authorization fields in the index;
- backend-owned Search filters;
- a stable authorization fingerprint in every cache key; and
- tests proving callers with different scopes cannot share entries.

### Model deployment is shared

The current `gpt-4o-mini` deployment supports the existing figure-understanding
and demo answer flows. Avoid running a high-volume ingestion and query load test
simultaneously unless quota has been validated. A separate chat deployment is
preferred when repeatable performance measurements matter.

### Cache failure behavior

Cache unavailability must behave as a miss, not as a successful empty response.
Rate limiting should protect the backend after cache lookup so an outage does
not create an uncontrolled load spike.

---

## Implementation phases

### Phase 0: repair observability

- Diagnose the current Application Insights ingestion gap.
- Prove structured query and dependency telemetry reaches Log Analytics.
- Define the shared correlation and telemetry contract.

### Phase 1: expose the existing RAG flow

- Create and validate the OpenSpec change.
- Implement the separate RAG Query API.
- Extract reusable retrieval and answer logic from `scripts/demo.py`.
- Add managed-identity RBAC.
- Add tests for normalization, retrieval, response shape, and failure handling.
- Validate one grounded request with citations.

### Phase 2: APIM exact-cache comparison

- Deploy APIM.
- Add baseline and built-in-cache operations.
- Implement opaque cache-key generation.
- Add knowledge-generation partitioning.
- Add cache-outcome headers and telemetry.
- Validate miss, hit, and generation-driven miss.

### Phase 3: external Redis

- Deploy Azure Managed Redis.
- Configure APIM external caching.
- Add the external-cache operation.
- Validate equivalent exact-cache behavior.
- Validate safe fallback during a controlled cache failure.

### Phase 4: application Redis

- Add one retrieval or embedding cache to the query application.
- Keep APIM-managed and application-managed keyspaces separate.
- Measure partial-work savings independently from response-cache savings.

### Phase 5: workbook and reusable demo package

- Deploy the Azure Monitor Workbook.
- Add the browser or CLI demo console.
- Parameterize names, TTLs, cache modes, corpus labels, and deployment options.
- Add a presenter runbook and pre-flight checks.

### Phase 6: selective semantic caching

- Build representative equivalent and non-equivalent query pairs.
- Configure the required embedding and Redis search capabilities.
- Tune the similarity threshold conservatively.
- Validate citations, version partitioning, and false-hit behavior.

---

## Proof-of-value success criteria

The extension is successful when:

- the same backend serves all comparison operations;
- an uncached repeated request invokes Search and the model each time;
- an APIM cache hit invokes neither Search nor the model;
- an APIM cache hit generates no new model input or output tokens;
- changing the knowledge generation forces a miss;
- APIM built-in and external Redis response caching can be compared using the
  same request and cache-key contract;
- application Redis can demonstrate partial RAG-work avoidance separately;
- cache failure falls back to the normal backend path;
- errors and filtered responses are not cached by default;
- every request can be correlated across APIM and the query backend;
- the workbook shows latency, hit rate, backend calls, Search calls, model
  calls, and tokens by cache mode; and
- no raw prompt or sensitive document content is required in cache keys or
  telemetry.

---

## Current OpenSpec implementation

The initial change focuses on the smallest complete exact-caching proof:

```text
add-apim-exact-cache-demo
```

Its approved scope is defined in
`openspec/changes/add-apim-exact-cache-demo/` and tracked by GitHub issue #11:

- separate HTTP RAG Query API;
- extraction of the existing retrieval and grounded-answer flow;
- baseline and APIM built-in-cache operations;
- knowledge-generation invalidation;
- cache and dependency telemetry; and
- miss, hit, and generation-change validation.

Keep external Redis, application caching, and semantic caching as follow-on
changes unless the first proposal demonstrates that they can be added without
making the initial proof difficult to validate or present.
