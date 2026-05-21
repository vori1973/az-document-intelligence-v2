## Why

Customer deployments on Azure AI Search (Standard tier) report HTTP 429 throttling under concurrent
user load, but without a reproducible test harness it is impossible to give concrete replica/partition
recommendations. This change adds an educational load-test tool that can simulate concurrent users
against the existing index, measure latency and throttle rates, and produce actionable scaling
suggestions — all without requiring access to a customer environment.

## What Changes

- New `scripts/load-test/` directory with three scripts and a KQL reference
- `embed_queries.py` — one-time utility to pre-embed a bank of domain-realistic queries via AOAI
- `load_test.py` — async concurrent runner (configurable concurrency, duration, query profile)
- `advisor.py` — reads result files, compares replica runs, prints replica/query recommendations
- `kql/` — Log Analytics queries customers can run to observe the same patterns in production
- `requirements.txt` — isolated dependencies (azure-search-documents, openai, aiohttp)
- `results/` and `query_bank.json` excluded from git via `.gitignore`

## Capabilities

### New Capabilities

- `search-load-test`: Concurrent load simulation against Azure AI Search with latency/429 metrics,
  before/after replica comparison, and a rule-based advisor for scaling recommendations

### Modified Capabilities

_(none — no existing spec-level behaviour changes)_

## Impact

- New files under `scripts/load-test/` only — no changes to pipeline code or shared modules
- Reuses existing env vars: `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_INDEX`, `AOAI_ENDPOINT`,
  `AOAI_EMBEDDING_DEPLOYMENT`
- Requires Standard tier Azure AI Search (to be able to add replicas)
- Adds new Python dependencies scoped to `scripts/load-test/requirements.txt` only
