## Purpose

Defines a demonstrable APIM exact-response cache mode backed by Azure Managed Redis so operators can compare uncached RAG execution, APIM built-in caching, and Redis-backed gateway caching using one backend and one cache identity contract.

## ADDED Requirements

### Requirement: Redis-backed APIM exact-cache operation
The system SHALL expose a Redis-backed demo query operation that uses Azure Managed Redis as APIM's external exact-response cache while preserving the same grounded RAG response contract as the baseline and built-in-cache operations.

#### Scenario: First Redis-cache request
- **WHEN** an eligible request with no matching Redis-backed cache entry is sent to the Redis-backed operation
- **THEN** APIM invokes the query backend, returns the backend response, and stores the successful response in the external cache for the configured TTL

#### Scenario: Repeated Redis-cache request
- **WHEN** the same eligible request is repeated within the configured TTL
- **THEN** APIM returns the stored response from the Redis-backed cache without invoking the query backend, Azure AI Search, or Azure OpenAI again

#### Scenario: Redis operation uses shared backend
- **WHEN** equivalent requests are sent through the baseline, built-in-cache, and Redis-backed operations
- **THEN** any backend executions use the same query backend and grounded-answer contract

### Requirement: Comparable built-in and Redis cache evidence
The system SHALL expose non-sensitive response metadata that distinguishes APIM built-in cache behavior from Azure Managed Redis cache behavior during the same presenter run.

#### Scenario: Cache type identifies Redis
- **WHEN** APIM returns a response from the Redis-backed operation
- **THEN** response metadata identifies the cache type as Redis-backed external APIM caching and reports the cache outcome, active knowledge generation, opaque cache-key identifier, and correlation identifier

#### Scenario: Same cache identity dimensions
- **WHEN** the same eligible question is submitted to built-in-cache and Redis-backed operations under the same trusted dimensions
- **THEN** both operations derive cache identity from normalized question, knowledge generation, security scope, prompt version, and logical model version

#### Scenario: Presenter comparison
- **WHEN** a presenter runs the demo comparison for one question
- **THEN** the output shows baseline behavior, built-in-cache miss/hit behavior, Redis-cache miss/hit behavior, elapsed time, citations, backend invocation metadata, and cache proof headers

### Requirement: Redis-backed generation invalidation
The system SHALL include the active knowledge generation in Redis-backed cache identity so corpus publication invalidates stale Redis-backed answers without requiring a bulk purge.

#### Scenario: Redis request after generation publication
- **WHEN** the active knowledge generation changes and a previously cached question is submitted through the Redis-backed operation
- **THEN** the request is a cache miss and the backend generates an answer against the active corpus

#### Scenario: Earlier Redis entries remain unreachable
- **WHEN** a new generation is published
- **THEN** Redis-backed entries from earlier generations become unreachable by new requests and may expire naturally by TTL

### Requirement: Redis cache eligibility and fallback behavior
The system SHALL cache only successful, explicitly eligible exact-query responses in Azure Managed Redis. Redis lookup, storage, or connectivity failure SHALL be treated as a protected cache miss or fallback and SHALL NOT produce a successful empty response.

#### Scenario: Redis stores only eligible success
- **WHEN** the backend returns an eligible successful JSON response for the Redis-backed operation
- **THEN** APIM may store that response in Azure Managed Redis for the configured TTL

#### Scenario: Redis does not store errors
- **WHEN** validation, backend, timeout, filtered, or non-query responses occur
- **THEN** APIM returns the response without storing it in Azure Managed Redis

#### Scenario: Redis unavailable
- **WHEN** APIM cannot read from or write to Azure Managed Redis
- **THEN** the request continues through the normal rate-limited backend path and response metadata records a cache fallback rather than a cache hit

### Requirement: Redis configuration security boundary
The system SHALL provision and configure Azure Managed Redis through repository-managed infrastructure. Any APIM-to-Redis connection credential required by the platform MUST be stored only as secure APIM configuration and MUST NOT be emitted in deployment outputs, response headers, telemetry, logs, scripts, or documentation examples.

#### Scenario: Redis connection credential is not exposed
- **WHEN** an operator inspects deployment outputs, demo output, response headers, or telemetry
- **THEN** the Redis connection string, access keys, credentials, and raw cache values are not present

#### Scenario: Managed identity remains the query dependency model
- **WHEN** the query backend accesses Azure AI Search or Azure OpenAI during a Redis-cache miss
- **THEN** it still authenticates with managed identity and does not use Redis credentials for query dependencies

#### Scenario: Redis credential exception is documented
- **WHEN** an operator reads the Redis demo deployment documentation
- **THEN** it explicitly states that APIM external cache integration requires a Redis connection string and that this is a constrained exception to the repository's managed-identity default

### Requirement: Redis telemetry comparison
The system SHALL correlate Redis-backed APIM requests with cache outcome and backend execution telemetry without logging raw questions, prompts, retrieved content, cached response bodies, Redis connection strings, access tokens, or direct user identifiers by default.

#### Scenario: Redis miss telemetry
- **WHEN** an eligible Redis-backed request misses and completes successfully
- **THEN** telemetry can correlate the APIM request with one backend invocation and its embedding, Search, and model dependency measurements

#### Scenario: Redis hit telemetry
- **WHEN** an eligible Redis-backed request hits
- **THEN** telemetry records the Redis-backed APIM hit with no correlated backend, Search, or model execution for that request

#### Scenario: Built-in versus Redis comparison
- **WHEN** an operator compares equivalent built-in-cache and Redis-backed traffic
- **THEN** telemetry supports comparison of request count, cache outcome, end-to-end latency, backend invocations, Search calls, model calls, token usage, and Redis fallback count
