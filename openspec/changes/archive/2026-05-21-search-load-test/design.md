## Context

The project already has an Azure AI Search index (`document-chunks`) populated by the ingestion
pipeline. The index uses HNSW vector search with scalar quantization and a semantic configuration.
The existing `scripts/load-test/README.md` describes the intended architecture in detail.

The tool targets Standard tier where replicas can be added/removed to illustrate scaling behaviour.
The audience is the developer running their own dev environment — not a production deployment.

## Goals / Non-Goals

**Goals:**
- Pre-embed a bank of domain-realistic queries once; reuse across all test runs
- Run N concurrent async workers for a configurable duration, recording per-request latency and status
- Support three query profiles: vector-only, hybrid, semantic
- Write timestamped JSON result files consumable by the advisor
- Advisor compares results across replica counts and prints recommendations with a replica estimate
- KQL reference doc for customers to run equivalent monitoring in their Log Analytics workspace

**Non-Goals:**
- Programmatic replica scaling (manual `az search service update` is sufficient for illustration)
- Benchmarking or capacity planning beyond educational illustration
- Multi-region or geo-distribution testing
- End-to-end RAG latency (embedding latency is excluded by design — query bank is pre-embedded)
- Integration with Application Insights or any telemetry sink

## Decisions

### D1: Pre-embedded query bank over on-the-fly embedding

**Decision:** Embed queries once into `query_bank.json`; load_test.py reads vectors directly.

**Rationale:** Eliminates AOAI latency from measurements — we want to isolate search latency.
AOAI rate limits would also cap concurrency artificially.

**Alternative considered:** Embed at query time. Rejected: AOAI adds 100–300ms per request,
masking the search signal. Also introduces a second rate-limit dimension.

---

### D2: asyncio + azure-search-documents async client

**Decision:** Use `asyncio.gather` with N coroutines, each looping for the test duration.

**Rationale:** The Azure Search SDK provides an async `SearchClient`. asyncio is lightweight
and avoids thread-per-worker overhead at higher concurrency levels (20–50+).

**Alternative considered:** `ThreadPoolExecutor` with sync client. Simpler but hits GIL at high
concurrency; async is cleaner for I/O-bound workloads.

---

### D3: `--replicas` as metadata label, not service configuration

**Decision:** The user passes `--replicas N` as a label written into the results JSON.
The script does not read or change the Azure Search service replica count.

**Rationale:** Keeps the tool stateless and permission-free. Manual scaling via
`az search service update` takes ~3 minutes; wrapping that in the script adds complexity
and requires Contributor role. For educational use, manual is sufficient.

**Alternative considered:** Programmatic scaling via Azure Management SDK. Deferred — could
be added later if the tool evolves into a pre-sales instrument.

---

### D4: Rule-based advisor over statistical modelling

**Decision:** Simple threshold rules (429 rate > 5%, p95 > 800ms, etc.) with a linear
replica estimate formula.

**Rationale:** The audience is a developer validating behaviour, not a capacity planner.
Simple rules are transparent and explainable. A statistical model would require more runs
and obscure the reasoning.

**Formula:** `replicas_needed = ceil(target_qps / (achieved_qps_at_1_replica))`
Add ~20% buffer for variance.

---

### D5: Isolated requirements.txt under scripts/load-test/

**Decision:** Separate `requirements.txt` from the main pipeline dependencies.

**Rationale:** The load test has different dependencies (aiohttp, tqdm) and is never deployed
to Azure Functions. Keeping them separate avoids polluting the Function App package.

## Risks / Trade-offs

- **Index size skews results** → Small sample dataset means lower latency than production;
  results are illustrative, not predictive. Document clearly in README.

- **Semantic ranker quota** → Semantic profile may hit the semantic ranker's own quota
  (separate from replica QPS). 429s under semantic profile may reflect ranker saturation,
  not replica saturation. Advisor should call this out.

- **query_bank.json not in git** → If lost, re-run embed_queries.py. Acceptable since
  the input queries are hardcoded in the script.

- **asyncio event loop on Windows** → WSL mitigates this, but note in README for native
  Windows users (use `asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())`).

## Open Questions

- How many queries in the bank? 20–50 feels right. More diversity = more representative;
  fewer = simpler to maintain. Start at 30.
- Should advisor output be machine-readable JSON in addition to human text?
  Deferred — human text is sufficient for educational use.
