## 1. Establish Query Telemetry

- [x] 1.1 Diagnose the existing Application Insights ingestion gap and document the configuration defect that prevents Python application telemetry from reaching the shared workspace.
- [x] 1.2 Correct the monitoring and application configuration in code/Bicep and add a focused test or deployment check for the required telemetry settings.
- [x] 1.3 Prove a synthetic query request and dependency event can be correlated in Log Analytics without logging question or document content.

## 2. Build the Reusable RAG Query Domain

- [x] 2.1 Extract the embedding, hybrid retrieval, grounded prompt, answer, and citation behavior from `scripts/demo.py` into reusable query modules without changing the demo script's existing behavior.
- [x] 2.2 Define typed request, response, citation, execution-metadata, and dependency-error contracts for the query path.
- [x] 2.3 Implement bounded question validation plus the documented trim, lowercase, whitespace-collapse, SHA-256 normalization and cache-key test vectors.
- [x] 2.4 Add structured correlation, dependency timing, called/not-called flags, backend invocation IDs, and available model token usage without recording raw query or retrieved content.
- [x] 2.5 Add unit tests for validation, normalization, retrieval result mapping, grounded response shape, citation behavior, telemetry redaction, and dependency failures.

## 3. Add the Separate Query Function App

- [x] 3.1 Create the non-Durable Python Function App entry point and package configuration for the shared RAG query implementation.
- [x] 3.2 Implement the internal HTTP query route with trusted context headers, correlation propagation, execution headers, `Server-Timing`, and explicit non-success error responses.
- [x] 3.3 Configure managed-identity clients for Azure AI Search and Azure OpenAI with no keys or connection strings in application settings.
- [x] 3.4 Add Function App tests for successful grounded queries, invalid payloads, dependency failures, caller-header replacement expectations, and response metadata.

## 4. Provision Query Infrastructure and Identity

- [x] 4.1 Add a Bicep module for the query Function App, separate hosting plan, managed identity, runtime settings, Application Insights connection, and configurable capacity limits.
- [x] 4.2 Add least-privilege role assignments granting the query identity Search Index Data Reader and Cognitive Services OpenAI User access.
- [x] 4.3 Configure App Service Authentication/Authorization so only the APIM managed identity and approved deployment/test principals can invoke the backend.
- [x] 4.4 Wire query deployment switches, resource names, endpoints, model versions, prompt version, and outputs through `infra/main.bicep` and the existing deployment workflow.
- [x] 4.5 Add or update infrastructure tests and run `az bicep build --file infra/main.bicep`.

## 5. Add APIM Baseline and Built-in Cache Operations

- [x] 5.1 Select and parameterize the lowest-cost target-region APIM SKU that supports the required custom cache, diagnostics, and managed-identity policies.
- [x] 5.2 Add the APIM service, managed identity, API/backend definition, diagnostics, and managed-identity authentication to the query Function App in Bicep.
- [x] 5.3 Implement `POST /rag/baseline` as an uncached operation that overwrites trusted context headers and forwards to the shared backend.
- [x] 5.4 Implement bounded JSON parsing, exact question normalization, opaque cache-key construction, and trusted generation/scope/prompt/model dimensions in APIM policy.
- [x] 5.5 Implement `POST /rag/apim-built-in` custom cache lookup/store policies that cache only eligible 2xx responses for the configurable TTL.
- [x] 5.6 Add cache outcome, cache type, active generation, opaque key ID, and correlation response headers for misses, hits, bypasses, and fallbacks.
- [x] 5.7 Add backend rate limiting, timeouts, and cache-failure handling so lookup/storage failures continue as protected misses rather than successful empty responses.

## 6. Add Generation Publication and Demo Validation

- [x] 6.1 Add the active knowledge generation as trusted deployment-managed APIM configuration with a non-secret default suitable for development.
- [x] 6.2 Add a guarded script or deployment command that publishes a new generation only after ingestion completion and a successful queryability check.
- [x] 6.3 Add a repeatable demo driver that invokes baseline and built-in-cache operations and displays response headers, elapsed time, citations, and backend invocation metadata.
- [x] 6.4 Add automated Azure integration scenarios for repeated baseline execution, built-in-cache miss/hit, normalization equivalence, changed cache dimensions, generation-driven miss, uncached errors, and direct-backend rejection.
- [x] 6.5 Verify telemetry distinguishes baseline, miss, hit, and fallback outcomes and proves backend, Search, model, and token avoidance on a cache hit.

## 7. Documentation and Final Validation

- [x] 7.1 Document deployment parameters, managed-identity roles, cache-key dimensions, TTL behavior, generation publication, and the controlled single-scope security limitation.
- [x] 7.2 Document the presenter sequence and expected evidence for baseline calls, first miss, repeated hit, and generation-change miss.
- [x] 7.3 Run the repository unit suite and targeted integration tests, then resolve regressions attributable to this change.
- [x] 7.4 Validate the completed OpenSpec change strictly and ensure all implemented tasks and scenarios are checked off before archive.
