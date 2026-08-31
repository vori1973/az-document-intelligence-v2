## Purpose

Defines a measurable HTTP RAG experience that compares uncached execution with APIM exact-response caching while preserving corpus-version correctness, privacy, and dependency observability.

## ADDED Requirements

### Requirement: Grounded RAG query contract
The system SHALL accept a JSON question request through the demo query operations and SHALL return a grounded answer, source citations, and execution metadata. A backend execution SHALL generate a query embedding, perform hybrid retrieval against the published document index, construct a grounded prompt, and invoke the configured chat model.

#### Scenario: Successful grounded query
- **WHEN** a caller submits a valid question to a demo query operation
- **THEN** the response contains an answer, zero or more source citations, a backend invocation identifier, and dependency execution metadata

#### Scenario: Invalid query request
- **WHEN** a caller submits a missing, empty, malformed, or over-limit question
- **THEN** the system rejects the request with a non-success status and does not cache the response

#### Scenario: Dependency failure
- **WHEN** embedding, retrieval, or answer generation fails
- **THEN** the system returns a non-success response with a correlation identifier and does not present a partial result as a successful cached answer

### Requirement: Comparable APIM operations
The system SHALL expose `/rag/baseline` and `/rag/apim-built-in` operations through APIM, and both operations SHALL use the same query backend and answer-generation contract.

#### Scenario: Repeated baseline request
- **WHEN** the same eligible request is sent twice to `/rag/baseline`
- **THEN** both requests invoke the query backend and produce distinct backend invocation identifiers

#### Scenario: First built-in-cache request
- **WHEN** an eligible request with no matching entry is sent to `/rag/apim-built-in`
- **THEN** APIM invokes the query backend, returns the backend response, and stores the successful response for the configured TTL

#### Scenario: Repeated built-in-cache request
- **WHEN** the same eligible request is repeated within the configured TTL
- **THEN** APIM returns the stored response without invoking the query backend, Azure AI Search, or Azure OpenAI again

### Requirement: Exact and opaque cache identity
The system SHALL derive exact-response cache identity from the normalized-question hash, knowledge generation, security scope, prompt version, and logical model version. Cache identifiers exposed in headers or telemetry MUST be opaque and MUST NOT contain raw questions, prompts, document content, credentials, access tokens, or direct user identifiers.

#### Scenario: Equivalent normalized question
- **WHEN** two requests differ only by the documented whitespace and case normalization rules
- **THEN** they resolve to the same normalized-question hash and cache identity

#### Scenario: Material cache dimension changes
- **WHEN** the normalized question, knowledge generation, security scope, prompt version, or logical model version differs
- **THEN** the requests resolve to different cache identities

#### Scenario: Cache identifier inspection
- **WHEN** an operator inspects response headers or telemetry for a cached request
- **THEN** only an opaque cache-key identifier is visible and no raw sensitive cache-key material is present

### Requirement: Knowledge-generation invalidation
The system SHALL use a backend-controlled active knowledge generation in every cache identity. The active generation SHALL change only after affected index updates complete and the newly published corpus is queryable.

#### Scenario: Request after generation publication
- **WHEN** the active knowledge generation changes and a previously cached question is submitted again
- **THEN** the request is a cache miss and the backend generates an answer against the active corpus

#### Scenario: Existing entries from an earlier generation
- **WHEN** a new generation is published
- **THEN** entries from earlier generations become unreachable by new requests without requiring a bulk cache purge

#### Scenario: Caller supplies cache partition values
- **WHEN** a caller supplies or alters generation, security-scope, prompt-version, or model-version values
- **THEN** APIM replaces or validates those values against trusted configuration before deriving the cache identity or forwarding the request

### Requirement: Cache eligibility and failure behavior
The system SHALL cache only successful, explicitly eligible exact-query responses. Errors, timeouts, filtered responses, ingestion operations, and delete operations MUST NOT be cached. Cache lookup or storage failure SHALL be treated as a cache miss and SHALL NOT produce a successful empty response.

#### Scenario: Successful eligible response
- **WHEN** the backend returns an eligible success response for `/rag/apim-built-in`
- **THEN** APIM may store that response for the configured TTL

#### Scenario: Backend error response
- **WHEN** the backend returns a non-success response
- **THEN** APIM returns the error without storing it in the response cache

#### Scenario: Cache subsystem failure
- **WHEN** APIM cannot read or write its built-in cache
- **THEN** the request continues through the normal protected backend path and the cache failure is recorded

### Requirement: Visible cache and dependency proof
The system SHALL expose non-sensitive response metadata sufficient to distinguish baseline execution, cache misses, and cache hits without requiring the presenter to inspect raw telemetry.

#### Scenario: Backend execution metadata
- **WHEN** the query backend executes
- **THEN** the response identifies the backend invocation and reports whether embedding, Search, and model dependencies were called, their durations when available, and model token usage when available

#### Scenario: Gateway cache outcome
- **WHEN** APIM returns a response from a demo query operation
- **THEN** response headers identify the cache outcome, cache type, active knowledge generation, opaque cache-key identifier, and correlation identifier

#### Scenario: Cache-hit proof
- **WHEN** APIM serves a built-in-cache hit
- **THEN** the response identifies the request as a cache hit and no new backend invocation, Search call, model call, or model token usage is recorded for that request

### Requirement: Correlated privacy-preserving telemetry
The system SHALL correlate APIM requests, backend executions, Search dependencies, and model dependencies in the shared monitoring environment. Telemetry SHALL distinguish cache mode and outcome and SHALL NOT log raw questions, retrieved chunk text, complete prompts, cached response bodies, secrets, access tokens, or direct user identifiers by default.

#### Scenario: Cache miss telemetry
- **WHEN** an eligible built-in-cache request misses and completes successfully
- **THEN** telemetry can correlate the APIM request with one backend invocation and its embedding, Search, and model dependency measurements

#### Scenario: Cache hit telemetry
- **WHEN** an eligible built-in-cache request hits
- **THEN** telemetry records the APIM hit with no correlated backend, Search, or model execution for that request

#### Scenario: Baseline comparison
- **WHEN** an operator compares equivalent baseline and built-in-cache traffic
- **THEN** telemetry supports comparison of request count, cache outcome, end-to-end latency, backend invocations, Search calls, model calls, and token usage

### Requirement: Managed identity and initial security boundary
The query backend SHALL use managed identity with least-privilege data-plane access to Azure AI Search and Azure OpenAI. APIM SHALL authenticate to the query backend independently of caller-supplied values. The initial demo SHALL use a public or single authorized corpus scope and MUST NOT represent a caller-provided `securityScope` value as tenant security trimming.

#### Scenario: Query dependency authentication
- **WHEN** the query backend accesses Azure AI Search or Azure OpenAI
- **THEN** it authenticates with its managed identity and no service key or connection string is required in application settings

#### Scenario: Direct backend access attempt
- **WHEN** a caller without the configured APIM-to-backend identity attempts to invoke the query backend directly
- **THEN** the backend rejects the request

#### Scenario: Initial scope presentation
- **WHEN** the demo displays or records a security-scope partition
- **THEN** it identifies the scope as cache partitioning for the controlled corpus rather than enforceable multitenant authorization
