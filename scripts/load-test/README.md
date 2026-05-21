# Azure AI Search — Load Test & Advisor

Educational load-testing tool for Azure AI Search (Standard tier).
Simulates concurrent users, measures latency and throttling (HTTP 429),
and produces actionable replica/partition recommendations.

Designed to illustrate before/after behaviour when scaling replicas —
without needing access to a customer environment.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  ONE-TIME SETUP                                                 │
│                                                                 │
│  embed_queries.py                                               │
│  ["what is the VELYS procedure?", "knee implant sizing", ...]   │
│         │                                                       │
│         ▼  Azure OpenAI  text-embedding-ada-002                 │
│  query_bank.json   (text + vector pairs, 20–50 queries)         │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  OPTIONAL — SEED THE INDEX  (Step 0)                            │
│                                                                 │
│  seed_index.py --chunks 50000                                   │
│                                                                 │
│  Generates random unit vectors + placeholder text fields        │
│  Uploads directly to Azure AI Search (bypasses pipeline)        │
│  Prefix synthetic- on all IDs → safe to delete with --delete   │
│                                                                 │
│  Without seeding: small dev index → zero 429s at any           │
│  concurrency (too cheap per query to saturate a replica)        │
│  With seeding:    realistic index size → 429s appear and        │
│  replica scaling produces measurable latency improvement        │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  LOAD TEST RUN                                                  │
│                                                                 │
│  load_test.py --concurrency 20 --duration 60 --profile hybrid  │
│               --replicas 1                                      │
│                                                                 │
│  asyncio workers, each randomly picking from the query bank,   │
│  firing requests, recording latency + HTTP status              │
│                                                                 │
│  Profiles:                                                      │
│    vector    vector search only (HNSW, no keyword)             │
│    hybrid    vector + keyword  (most common production shape)   │
│    semantic  hybrid + semantic reranking  (highest cost)        │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  RESULTS  results/2026-05-21T14-30_c20_hybrid_r1/              │
│                                                                 │
│  summary.json  — aggregated stats (read by advisor.py)         │
│  {                                                              │
│    "concurrency": 20,   "profile": "hybrid",                   │
│    "replicas": 1,       "duration_s": 60,                       │
│    "total_requests": 487,  "successful": 451,                   │
│    "throttled_429": 36,    "throttle_pct": 7.4,                 │
│    "p50_ms": 210,   "p95_ms": 890,   "p99_ms": 1840,           │
│    "achieved_qps": 7.5                                          │
│  }                                                              │
│                                                                 │
│  log.jsonl  — per-request detail (only with --log-requests)    │
│  {"seq":0,"query":"knee implant sizing","profile":"hybrid",     │
│   "latency_ms":87.6,"results":[{"score":0.032,                 │
│   "reranker_score":null,"source_file":"guide.pdf",...}]}        │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  ADVISOR                                                        │
│                                                                 │
│  advisor.py results/                                            │
│                                                                 │
│  Compares runs across replica counts                            │
│  Applies threshold rules → prints human-readable suggestions   │
│  Outputs: replica recommendation, query optimization hints,     │
│           KQL queries to run in customer Log Analytics          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
scripts/load-test/
  README.md               this file
  embed_queries.py        one-time: embed a set of text queries via AOAI
  seed_index.py           inject synthetic chunks to reach realistic index size
  load_test.py            async load runner (concurrency, duration, profile)
  advisor.py              reads results/ → prints recommendations
  query_bank.json         pre-embedded queries (gitignored)
  kql/
    README.md             how to enable diagnostics and run KQL queries
    throttling.kql        429 rate by 5-minute window
    latency.kql           p50/p95/p99 latency trend
    semantic-impact.kql   before/after latency comparison for semantic ranker
  results/                raw run output (gitignored)
    <timestamp>_cN_PROFILE_rN/
      summary.json        aggregated stats — read by advisor.py
      log.jsonl           per-request detail (only when --log-requests)
  advisory/               generated Markdown reports (committed)
    <timestamp>_report.md
  requirements.txt
  .env                    your env vars (gitignored, create from example below)
```

---

## Azure AI Search — Standard Tier Reference

| Resource        | Limit                          |
|-----------------|--------------------------------|
| Replicas        | 1–12                           |
| Partitions      | 1–12  (160 GB each)            |
| Search units    | replicas × partitions, max 36  |
| Min for SLA     | 2 replicas (read), 3 (r/w)     |

**For this test:** sample documents fit comfortably in 1 partition.
Only replica count is varied. Partitions are irrelevant at this data size.

**How replicas help:**
Each replica handles a share of query load independently.
Adding replicas increases QPS capacity and reduces latency under load —
it does not increase storage or index size.

---

## Setup

### Prerequisites

- Python 3.11+
- Azure AI Search (Standard tier) with an existing index
- Azure OpenAI endpoint with `text-embedding-ada-002` deployment
- `DefaultAzureCredential` configured (same MI/identity as the main pipeline)

### RBAC requirements

The identity running the scripts needs the following roles:

| Script | Role required | Scope |
|---|---|---|
| `embed_queries.py` | `Cognitive Services User` | Azure OpenAI resource |
| `load_test.py` | `Search Index Data Reader` | Azure AI Search service |
| `seed_index.py` | `Search Index Data Contributor` | Azure AI Search service |

`Search Index Data Reader` is read-only — it is not sufficient for seeding.
`seed_index.py` writes documents and requires `Search Index Data Contributor`.

Assign to your developer identity (one-time):

```bash
# Get your user object ID
USER_OID=$(az ad signed-in-user show --query id -o tsv)

# Search Index Data Reader — required for load_test.py
az role assignment create \
  --role "Search Index Data Reader" \
  --assignee $USER_OID \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Search/searchServices/<service>

# Search Index Data Contributor — required for seed_index.py
az role assignment create \
  --role "Search Index Data Contributor" \
  --assignee $USER_OID \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Search/searchServices/<service>

# Cognitive Services User — required for embed_queries.py
az role assignment create \
  --role "Cognitive Services User" \
  --assignee $USER_OID \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<aoai-resource>
```

Allow 1–2 minutes for RBAC propagation before running the scripts.

> **Note:** API key auth is disabled by policy on this service. Do not add
> `AZURE_SEARCH_API_KEY` to your `.env` — `DefaultAzureCredential` is the only
> supported auth method.

### Install

```bash
# From the project root — uses the shared root .venv (Python 3.13)
pip install -r scripts/load-test/requirements.txt

# Activate before running scripts
source .venv/bin/activate
```

### Environment variables

Create `scripts/load-test/.env` (gitignored):

```bash
export AZURE_SEARCH_ENDPOINT="https://<name>.search.windows.net"
export AZURE_SEARCH_INDEX="document-chunks"
export AOAI_ENDPOINT="https://<name>.openai.azure.com/"
export AOAI_EMBEDDING_DEPLOYMENT="text-embedding-ada-002"
```

Then source before each session:

```bash
source scripts/load-test/.env
```

---

## Step 0 — Seed the Index (optional)

The load test only triggers HTTP 429 throttling if the index is large enough to
saturate a replica. A small development index (a few hundred documents) costs the
service almost nothing per query — you will see low latency and zero 429s regardless
of concurrency. Use `seed_index.py` to inject synthetic chunks at realistic scale
before load testing.

Synthetic chunks use random unit vectors (1536-dim) and placeholder text that
conform to the `document-chunks` index schema. All IDs are prefixed with
`synthetic-` so they are always distinguishable from real indexed documents.

### RBAC requirement

`seed_index.py` writes documents — it needs `Search Index Data Contributor`, not
just `Search Index Data Reader`. Assign it once to your developer identity:

```bash
USER_OID=$(az ad signed-in-user show --query id -o tsv)

az role assignment create \
  --role "Search Index Data Contributor" \
  --assignee $USER_OID \
  --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Search/searchServices/<service>
```

Wait 1–2 minutes for RBAC propagation before running the script.

### When to seed

| Goal | `--chunks` value | Approximate size |
|---|---|---|
| Verify the tool works | 1,000 | ~6 MB |
| Light realism check | 10,000 | ~60 MB |
| Typical customer index | 50,000 | ~300 MB |
| Large customer index | 200,000 | ~1.2 GB |

### Seed the index

```bash
# Seed 50,000 synthetic chunks (recommended starting point)
python seed_index.py --chunks 50000

# Custom batch size (default 500; max 1000 per Azure SDK limit)
python seed_index.py --chunks 50000 --batch-size 200
```

Progress is printed per batch:

```
Seeding 50,000 synthetic chunks in batches of 500...
  Batch 1/100 (500 docs) | cumulative: 500 | elapsed: 1.2s | 416 chunks/sec
  Batch 2/100 (500 docs) | cumulative: 1,000 | elapsed: 2.3s | 435 chunks/sec
  ...
Done. Uploaded 50,000 synthetic chunks in 115.4s (433 chunks/sec).
Wait 2-5 minutes for the HNSW graph to stabilise before running the load test.
```

Wait **2–5 minutes** after seeding. The HNSW graph needs time to stabilise
after a bulk upload — running the load test immediately will produce lower
latency than a production index at rest.

### Delete synthetic chunks after testing

```bash
# Remove all synthetic chunks — real documents are untouched
python seed_index.py --delete
```

Output:

```
Searching for synthetic chunks...
Found 50,000 synthetic chunks. Deleting...
  Deleted 500/50,000
  Deleted 1,000/50,000
  ...
Done. Deleted 50,000 synthetic chunks.
```

### Common errors

| Error | Cause | Fix |
|---|---|---|
| `Permission denied (HTTP 403)` | Missing `Search Index Data Contributor` role | Run the `az role assignment create` command above and wait 1–2 min |
| `Unauthenticated (HTTP 401)` | No Azure credential available | Run `az login` first |
| `Bad request (HTTP 400)` | Index schema changed, or an OData filter function not supported by the API version | Compare `make_synthetic_chunk()` in `seed_index.py` against `step7_search.py` field definitions |
| `AZURE_SEARCH_ENDPOINT not set` | Missing environment variable | Source `scripts/load-test/.env` before running |

The script prints a clear error message for each of these cases and exits immediately
without a Python traceback.

---

## Step 1 — Generate the Query Bank (one-time)

The query bank is a JSON file of pre-embedded queries.
Pre-embedding means the AOAI call happens once, not on every test request —
so the load test measures pure search latency, not embedding latency.

```bash
python embed_queries.py
# writes query_bank.json
```

Queries are domain-realistic for the sample medical device documents:

- "recommended surgical technique for total knee replacement"
- "VELYS robotic system setup and calibration"
- "sports medicine implant sizing guide"
- "knee arthroplasty contraindications"
- "instrument sterilization requirements"
- ... (20–30 total)

To add your own queries, edit the `QUERIES` list in `embed_queries.py`.

---

## Step 2 — Run a Load Test

```bash
./scripts/load-test/load_test.py \
  --concurrency 10 \
  --duration 60 \
  --profile hybrid \
  --replicas 1
```

| Flag              | Default  | Description                                                      |
|-------------------|----------|------------------------------------------------------------------|
| `--concurrency`   | 10       | Number of simulated concurrent users (async workers)             |
| `--duration`      | 60       | How long to run in seconds — all workers stop when time is up    |
| `--profile`       | hybrid   | Query shape: `vector` / `hybrid` / `semantic`                    |
| `--replicas`      | 1        | Label written to results — does not change the service           |
| `--log-requests`  | off      | Write per-request detail to `log.jsonl` in the run directory     |

### How concurrency and duration work

```
start
  │
  ├── worker 0 ──┐
  ├── worker 1   │  Each worker loops independently for --duration seconds:
  ├── worker 2   │    1. Pick a random query from query_bank.json
  │   ...        │    2. Send it to Azure AI Search (async, no waiting for others)
  └── worker N ──┘    3. Record latency + HTTP status
                       4. Repeat immediately — no think time, no pause
  │
  └── after --duration seconds, all workers stop
      aggregate all recorded (status, latency_ms) pairs → summary.json
```

`--concurrency 10` means 10 workers fire queries in parallel at all times —
analogous to 10 simultaneous users each continuously sending requests with no
pause between them. This is a **sustained stress model**, not a gradual ramp.
Real user traffic has think time; multiply your peak concurrent users by ~0.3
to get an equivalent concurrency value for this tool.

Each worker picks a **different random query** from the bank on every request,
so the 30 pre-embedded queries are distributed across all workers throughout
the run.

### Query profiles

| Profile    | What it sends                         | Relative cost |
|------------|---------------------------------------|---------------|
| `vector`   | Vector search only (HNSW)             | Medium        |
| `hybrid`   | Vector + keyword (BM25)               | Medium–High   |
| `semantic` | Hybrid + semantic reranking           | High          |

Start with `hybrid` — it represents the most common production query shape
when using a Foundry/RAG agent.

---

## Step 3 — Before/After Replica Comparison

This is the core illustration. Run the same test at 1 replica and 3 replicas.

### Workflow

```
1. Confirm current replica count:
   az search service show \
     --name <service> --resource-group <rg> \
     --query "properties.replicaCount"

2. Run test at 1 replica:
   python load_test.py --concurrency 20 --duration 60 \
     --profile hybrid --replicas 1

3. Scale up:
   az search service update \
     --name <service> --resource-group <rg> \
     --replica-count 3
   # Wait ~3 minutes for provisioning

4. Run test at 3 replicas (same concurrency and profile):
   python load_test.py --concurrency 20 --duration 60 \
     --profile hybrid --replicas 3

5. Compare:
   python advisor.py results/
```

### Expected pattern

```
Concurrency → 20 concurrent users, hybrid profile

Replicas = 1                    Replicas = 3
────────────────────────────    ────────────────────────────
p50  latency:  210 ms           p50  latency:   95 ms
p95  latency:  890 ms           p95  latency:  180 ms
429  rate:     7.4%             429  rate:      0.0%
achieved QPS:  7.5              achieved QPS:  19.1
```

Numbers are illustrative. Actual values depend on query complexity,
document count, and index size.

---

## Step 3b — Before/After Semantic Ranker Comparison

This illustrates the latency cost of enabling the semantic re-ranker.
The index already includes a semantic configuration — only the service-level
feature needs to be enabled (no reindexing required).

### Workflow

```
1. Run hybrid profile first (works without semantic ranker):
   python load_test.py --concurrency 10 --duration 60 \
     --profile hybrid --replicas 1

2. Enable semantic ranker (free tier — 1,000 queries/month, no downtime):
   az search service update \
     --name <service> --resource-group <rg> \
     --semantic-search free
   # Takes ~1 minute

3. Run the same concurrency with semantic profile:
   python load_test.py --concurrency 10 --duration 60 \
     --profile semantic --replicas 1

4. Compare:
   python advisor.py results/
```

If you run step 3 before step 2, the script will exit with a clear error
message and the exact `az` command to enable the semantic ranker.

### What semantic ranking does

The semantic ranker is a **re-ranking step** applied after hybrid retrieval:

```
Query
  │
  ▼
Hybrid retrieval (vector HNSW + BM25 keyword, merged by RRF)
  │  top-50 candidates
  ▼
Semantic re-ranker (neural L2 model, scores by relevance to query intent)
  │  top-N re-ranked results
  ▼
Response
```

- **Without semantic ranker:** results ordered by RRF fusion score
- **With semantic ranker:** results re-ordered by natural language relevance
- The re-ranking adds latency but does not retrieve more documents
- Useful when query intent is complex or ambiguous

### Expected pattern

```
Concurrency → 10 concurrent users, 1 replica

Profile = hybrid                Profile = semantic
────────────────────────────    ────────────────────────────
p50  latency:   95 ms           p50  latency:  180 ms
p95  latency:  210 ms           p95  latency:  420 ms
429  rate:      0.0%            429  rate:      0.0%
achieved QPS:  9.2              achieved QPS:  8.1
```

The semantic ranker adds ~100–200ms per request at low concurrency.
Under high concurrency, the ranker has its own quota — you may see
latency climb without 429s (ranker saturation, not replica saturation).
The advisor will flag this as `[SEMANTIC_QUOTA]`.

---

## Step 4 — Advisor Output

```bash
# Console report
./scripts/load-test/advisor.py results/

# Console + save Markdown to advisory/
./scripts/load-test/advisor.py results/ --report
```

The advisor reads all `summary.json` files under `results/`, groups by profile and
replica count, prints findings and recommendations, and optionally saves a Markdown
report to `advisory/<timestamp>_report.md`.

### Why the Semantic Ranker Impact table only shows hybrid vs semantic

```
vector   = HNSW vector search only (no keyword)
hybrid   = HNSW vector + BM25 keyword, merged by RRF
semantic = hybrid + neural L2 re-ranker on the top-50 hybrid candidates
                    ↑_______________________________________↑
                    the impact table isolates exactly this step
```

Comparing `hybrid` → `semantic` shows the pure ranker cost (latency + QPS).
`vector` uses different retrieval so including it would conflate two changes at once.
The full three-way comparison is always visible in the main profile table.

### Example output

```
=== Azure AI Search Load Test Report ===

--- Profile: hybrid ---
  Replicas=1  concurrency=10  duration=60s  requests=551  p95=210ms  429_rate=0.0%  QPS=9.2

--- Profile: semantic ---
  Replicas=1  concurrency=10  duration=60s  requests=487  p95=420ms  429_rate=0.0%  QPS=8.1

--- Semantic Ranker Impact (hybrid vs semantic, same concurrency) ---
  Replicas   Profile    p50 ms   p95 ms   p99 ms   429 rate     QPS
  ---------------------------------------------------------------
         1    hybrid        72      210      380      0.0%     9.2
         1  semantic       155      420      780      0.0%     8.1

  Semantic ranker p95 overhead @ 1 replica(s): +210ms (+100%)

  NOTE: The semantic ranker re-ranks hybrid results using a neural model.
  Higher latency reflects the re-ranking step, not replica saturation.

Findings:
  [HEALTHY]  hybrid profile @ 1 replica(s): p95=210ms, 429_rate=0.0%
  [LATENCY]  semantic profile p95=420ms with 0% throttle rate. High latency
             without throttling suggests query complexity rather than replica saturation.

Recommendations:
  1. Check semantic reranking scope and query complexity...

Log Analytics queries: kql/README.md
```

---

## Advisor — Threshold Rules

| Condition                              | Recommendation                          |
|----------------------------------------|-----------------------------------------|
| 429 rate > 5%                          | Add replicas; calculate N from QPS ratio |
| 429 rate 1–5%                          | Early warning; add 1–2 replicas         |
| p95 > 800ms, 429 rate = 0%            | Query complexity; check semantic use    |
| p95 > 1000ms, profile = semantic      | Reduce semantic result window           |
| p95 < 300ms, 429 rate = 0%            | Healthy at current concurrency          |

**Replica estimate formula:**

```
replicas_needed = ceil(target_qps / (achieved_qps_at_1_replica))
```

This is a lower bound — network jitter and query variance add ~20% buffer.

---

## KQL Reference

See `kql/README.md` for queries to run in a customer's Log Analytics workspace.

Covers:
- 429 throttle rate by 5-minute window
- p50/p95/p99 latency trend
- Query volume and QPS

**Honest caveat:** Azure Search diagnostics do not expose replica-level
saturation as a direct metric. The signal is inferred from the pattern:
latency climbing + 429s appearing + QPS plateau. The KQL queries surface
this pattern — they do not report a single "replica full" number.

---

## Limitations

- **Not a benchmark:** results reflect this index size and query bank.
  Scale characteristics differ with larger indexes and different query shapes.
- **Replica metadata is manual:** `--replicas` is a label you provide;
  the tool does not read or change the Azure Search service configuration.
- **Embedding latency excluded:** the query bank pre-embeds all queries,
  so results show search-only latency, not end-to-end RAG latency.
- **Single region:** no cross-region latency or geo-distribution effects.
