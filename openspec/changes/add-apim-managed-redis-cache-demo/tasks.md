## 1. Redis Infrastructure

- [ ] 1.1 Verify the target-region Azure Managed Redis resource type, API version, lowest acceptable demo SKU, and APIM external-cache ARM shape before editing Bicep.
- [ ] 1.2 Add Redis deployment parameters to `infra/main.bicep` and environment parameter examples, defaulting Redis off so existing deployments remain unchanged.
- [ ] 1.3 Add a Bicep module that provisions Azure Managed Redis with secure defaults, configurable SKU/capacity/network settings, and no secret outputs.
- [ ] 1.4 Wire Redis outputs into the APIM module only when APIM and Redis are both enabled.
- [ ] 1.5 Configure APIM external cache registration for the gateway location or default scope using secure Redis connection configuration.
- [ ] 1.6 Add infrastructure tests proving Redis is optional, provisioned only by explicit switch, registered with APIM, and never exposes keys or connection strings in outputs.

## 2. APIM Redis Operation and Policy

- [ ] 2.1 Add `POST /rag/apim-redis` to the APIM API definition, backed by the same query backend as `/rag/baseline` and `/rag/apim-built-in`.
- [ ] 2.2 Add a Redis operation policy that mirrors built-in exact-cache lookup/store behavior while using APIM external cache semantics.
- [ ] 2.3 Set Redis-specific proof metadata, including cache type, cache outcome, key ID, generation, correlation ID, cached backend invocation ID, store result, and TTL.
- [ ] 2.4 Preserve the shared API-scope request validation, trusted header replacement, cache-key construction, backend authentication, rate limiting, and timeout behavior.
- [ ] 2.5 Verify APIM external cache fallback behavior in the chosen policy mode and adjust the policy only if needed to avoid false hits or empty success responses.
- [ ] 2.6 Add policy tests proving built-in and Redis operations share the same backend and identity contract but use separate internal versus external cache stores.

## 3. Security and Credential Handling

- [ ] 3.1 Document the APIM-to-Redis connection-string requirement as a constrained platform exception to the repository's managed-identity default.
- [ ] 3.2 Ensure Redis connection material is stored only as secure APIM configuration and is not printed by deployment scripts or demo tooling.
- [ ] 3.3 Add static tests that scan Redis Bicep, APIM Bicep, policies, scripts, and docs for accidental Redis key, connection-string, or cache-value exposure.
- [ ] 3.4 Confirm the query backend receives no Redis credentials and continues to use managed identity for Search and Azure OpenAI during Redis-cache misses.

## 4. Demo Driver and Documentation

- [ ] 4.1 Extend `scripts/demo_apim_cache.py` so a normal run compares baseline, APIM built-in cache, and APIM Redis cache for the same question.
- [ ] 4.2 Add CLI switches for skipping Redis comparison when Redis is not deployed and for emitting JSON that includes Redis cache results.
- [ ] 4.3 Update `docs/APIM-EXACT-CACHE-DEMO.md` with Redis deployment parameters, credential handling, presenter sequence, expected headers, and troubleshooting.
- [ ] 4.4 Update `docs/APIM-CACHING-EXTENSIBILITY.md` so the Redis exact-cache phase points to this implemented change and keeps application/semantic caching as follow-ons.
- [ ] 4.5 Update `scripts/deploy.sh` summary output to print the Redis-backed operation URL and safe next-step commands without printing Redis secrets.

## 5. Azure Integration Scenarios

- [ ] 5.1 Extend integration-test configuration with Redis gateway variables and skip behavior that keeps default local test runs offline.
- [ ] 5.2 Add a Redis miss-then-hit scenario proving the repeated request avoids backend, Search, Azure OpenAI, and new token usage.
- [ ] 5.3 Add Redis normalization-equivalence and trusted-dimension-change scenarios.
- [ ] 5.4 Add Redis generation-change validation showing old Redis entries become unreachable without a bulk purge.
- [ ] 5.5 Add Redis uncached-error validation proving invalid and non-success responses are not stored.
- [ ] 5.6 Add best-effort Redis telemetry validation showing Redis hits have APIM telemetry but no correlated backend work.

## 6. Validation

- [ ] 6.1 Run targeted query, APIM policy, infrastructure, script, and documentation-related tests.
- [ ] 6.2 Run `az bicep build --file infra/main.bicep`.
- [ ] 6.3 Run the repository unit suite.
- [ ] 6.4 Validate the completed OpenSpec change with `openspec validate add-apim-managed-redis-cache-demo --strict`.
- [ ] 6.5 Run the Redis-enabled live demo flow in Azure and capture the expected baseline, built-in miss/hit, Redis miss/hit, and generation-change evidence before archive.
