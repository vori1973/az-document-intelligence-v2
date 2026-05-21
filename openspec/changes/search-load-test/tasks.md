## 1. Project scaffold

- [x] 1.1 Create `scripts/load-test/requirements.txt` with dependencies: `azure-search-documents`, `openai`, `azure-identity`, `aiohttp`, `tqdm`
- [x] 1.2 Create `scripts/load-test/kql/README.md` explaining how to enable Search diagnostics and link to Log Analytics

## 2. Query bank — embed_queries.py

- [x] 2.1 Write `embed_queries.py` with a hardcoded `QUERIES` list of 30 domain-realistic medical device queries
- [x] 2.2 Implement AOAI embedding call using `DefaultAzureCredential` and env vars (`AOAI_ENDPOINT`, `AOAI_EMBEDDING_DEPLOYMENT`)
- [x] 2.3 Write output to `query_bank.json` as `[{"text": "...", "vector": [...]}]`

## 3. Load runner — load_test.py

- [x] 3.1 Implement CLI argument parsing: `--concurrency`, `--duration`, `--profile`, `--replicas`
- [x] 3.2 Implement `run_worker()` async coroutine: loop until duration elapsed, pick random query from bank, fire request, record latency + status code
- [x] 3.3 Implement `build_search_request()` for each profile — `vector`, `hybrid`, `semantic` — constructing the correct `SearchClient` call
- [x] 3.4 Aggregate results: `total_requests`, `successful`, `throttled_429`, `throttle_pct`, `p50_ms`, `p95_ms`, `p99_ms`, `achieved_qps`
- [x] 3.5 Write timestamped results file to `results/YYYY-MM-DDTHH-MM_cN_PROFILE_rN.json`
- [x] 3.6 Print live progress to stdout (requests/s, 429 count) using `tqdm` or simple counters

## 4. Advisor — advisor.py

- [x] 4.1 Read and parse all JSON files from `results/` directory
- [x] 4.2 Group results by replica count; within each group, aggregate by profile
- [x] 4.3 Apply threshold rules and emit findings: THROTTLING (>5%), LATENCY (p95>800ms, no 429s), SEMANTIC_QUOTA (semantic profile + p95>1000ms), HEALTHY
- [x] 4.4 Print replica recommendation with formula: `ceil(target_qps / (achieved_qps / replicas))` + 20% buffer
- [x] 4.5 Print before/after comparison table when multiple replica counts exist for the same profile
- [x] 4.6 Print pointer to `kql/README.md` at end of advisor output

## 5. KQL reference

- [x] 5.1 Write `kql/throttling.kql` — 429 rate by 5-minute window with columns: `TimeGenerated`, `total`, `throttled`, `throttle_pct`
- [x] 5.2 Write `kql/latency.kql` — p50/p95/p99 latency trend by 5-minute window with columns: `TimeGenerated`, `p50`, `p95`, `p99`, `qps`

## 6. Verify

- [x] 6.1 Run `embed_queries.py` — confirm `query_bank.json` is created with 30 entries, each containing a 1536-float vector
- [ ] 6.2 Run `load_test.py --concurrency 5 --duration 30 --profile hybrid --replicas 1` — confirm result file written with all required fields
- [ ] 6.3 Run `advisor.py results/` — confirm output prints findings and recommendations without errors
- [ ] 6.4 Reproduce a 429 by increasing `--concurrency` until throttling is observed; confirm it is counted not raised
