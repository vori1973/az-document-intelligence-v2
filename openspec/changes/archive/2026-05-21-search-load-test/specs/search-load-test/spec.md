## ADDED Requirements

### Requirement: Query bank generated from domain-realistic text queries
`embed_queries.py` SHALL accept a hardcoded list of text queries, call the Azure OpenAI
embeddings API, and write the result to `query_bank.json` as an array of
`{text, vector}` objects.

#### Scenario: Successful query bank generation
- **WHEN** `embed_queries.py` is run with valid AOAI credentials
- **THEN** `query_bank.json` is written containing at least 20 entries, each with a `text`
  string and a `vector` array of 1536 floats

#### Scenario: Existing query bank is overwritten
- **WHEN** `query_bank.json` already exists and `embed_queries.py` is run again
- **THEN** the file is overwritten with freshly embedded vectors

---

### Requirement: Async load runner supports configurable concurrency and profiles
`load_test.py` SHALL run N concurrent async workers for a specified duration,
each randomly selecting queries from `query_bank.json` and sending them to
Azure AI Search using the configured query profile.

#### Scenario: Vector profile sends vector-only search request
- **WHEN** `--profile vector` is used
- **THEN** each request is a pure vector search with no keyword component and no semantic reranking

#### Scenario: Hybrid profile sends vector + keyword request
- **WHEN** `--profile hybrid` is used
- **THEN** each request combines vector search with BM25 keyword search

#### Scenario: Semantic profile sends hybrid + semantic reranking request
- **WHEN** `--profile semantic` is used
- **THEN** each request uses hybrid search with semantic reranking enabled via the index's
  semantic configuration

#### Scenario: Results written to timestamped JSON file
- **WHEN** a load test run completes
- **THEN** a JSON file is written to `results/` named
  `YYYY-MM-DDTHH-MM_cN_PROFILE_rN.json` containing: `concurrency`, `profile`, `replicas`,
  `duration_s`, `total_requests`, `successful`, `throttled_429`, `throttle_pct`,
  `p50_ms`, `p95_ms`, `p99_ms`, `achieved_qps`

#### Scenario: 429 responses are counted but do not stop the run
- **WHEN** Azure Search returns HTTP 429 during a run
- **THEN** the response is counted in `throttled_429` and the worker continues without
  raising an exception

---

### Requirement: Advisor compares runs and prints scaling recommendations
`advisor.py` SHALL read all JSON files in `results/`, group them by replica count,
and print a human-readable report with findings and recommendations.

#### Scenario: Throttling detected — replica recommendation issued
- **WHEN** any result file has `throttle_pct > 5`
- **THEN** the advisor prints a THROTTLING finding and recommends a specific replica count
  calculated as `ceil(target_qps / (achieved_qps / replicas))`

#### Scenario: High latency without throttling — query optimisation hint issued
- **WHEN** `p95_ms > 800` and `throttle_pct == 0`
- **THEN** the advisor prints a LATENCY finding and suggests checking semantic reranking scope

#### Scenario: Before/after comparison shown when multiple replica counts present
- **WHEN** result files exist for more than one replica count with the same profile
- **THEN** the advisor prints a side-by-side comparison of p95 and 429 rate, and calculates
  the percentage improvement

#### Scenario: Healthy result acknowledged
- **WHEN** `p95_ms < 300` and `throttle_pct == 0`
- **THEN** the advisor reports the service is within acceptable bounds at current concurrency

---

### Requirement: KQL reference provides customer-runnable Log Analytics queries
The `kql/` directory SHALL contain a `README.md` and at least two `.kql` files
covering throttling rate and latency percentiles, usable in any Azure Log Analytics
workspace connected to an Azure AI Search diagnostic setting.

#### Scenario: Throttling KQL returns 429 rate by 5-minute window
- **WHEN** `throttling.kql` is run in Log Analytics against a Search service with diagnostics enabled
- **THEN** results show columns: `TimeGenerated`, `total`, `throttled`, `throttle_pct`
  grouped in 5-minute bins

#### Scenario: Latency KQL returns p50/p95/p99 by 5-minute window
- **WHEN** `latency.kql` is run in Log Analytics
- **THEN** results show columns: `TimeGenerated`, `p50`, `p95`, `p99`, `qps`
  grouped in 5-minute bins
