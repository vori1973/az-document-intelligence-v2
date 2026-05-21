## Context

The load test harness (`scripts/load-test/`) cannot produce HTTP 429 throttling
against the current development index because the index is too small — each query
costs the service almost nothing, so replicas never saturate regardless of
concurrency. Customer indexes are typically 10–50GB. A seeding utility that injects
synthetic chunks directly (bypassing OCR, chunking, and embedding) is needed to
create a representative index size cheaply and quickly.

The existing index schema (`document-chunks`) is defined and managed by `step7_search.py`.
The synthetic chunks must conform to that schema exactly.

## Goals / Non-Goals

**Goals:**
- Generate and upload N synthetic chunks directly to the Azure AI Search index
- Use random unit vectors (1536-dim) to populate the `embedding` field
- Match the existing schema fields exactly so no index changes are required
- Prefix all synthetic document IDs with `synthetic-` for easy identification
- Support `--delete` mode to remove all synthetic chunks after testing
- Print progress and a final summary (chunks uploaded, time taken)

**Non-Goals:**
- Realistic text content — placeholder text is sufficient for load testing
- Running the ingestion pipeline (OCR, chunking, AOAI embedding)
- Modifying the index schema
- Seeding any index other than the one in `AZURE_SEARCH_INDEX`

## Decisions

### D1: Random unit vectors over real embeddings

**Decision:** Generate random 1536-dim vectors, normalise to unit length.

**Rationale:** The HNSW graph's traversal cost depends on index size and graph
connectivity, not on whether vectors are semantically meaningful. Random unit
vectors distributed across the hypersphere produce a well-connected graph that
exercises the search engine realistically. Generating real embeddings would cost
money and require AOAI credentials for a utility whose only purpose is to
stress the search engine.

**Alternative considered:** Copy vectors from existing chunks. Rejected — clustered
vectors produce an unrepresentative HNSW graph (all neighbours in the same region).
Random vectors are more realistic for diverse production workloads.

---

### D2: `synthetic-` prefix on document and chunk IDs

**Decision:** All injected chunk IDs follow `synthetic-<uuid>`, document IDs follow
`synthetic-doc-<N>`.

**Rationale:** Allows `--delete` mode to filter and remove synthetic data without
touching real indexed documents. Simple prefix filter in the Search query.

**Alternative considered:** A separate index. Rejected — requires index management
overhead and doesn't test the same index the load test queries against.

---

### D3: Direct `SearchClient.upload_documents` — no pipeline

**Decision:** Use the Azure Search SDK directly, identical to `step7_search.py`'s
upload path. Batches of 500 documents.

**Rationale:** The pipeline (Durable Functions, blob triggers, OCR) adds latency
and cost irrelevant to the seeding goal. Direct SDK upload is simple and fast —
~500 chunks/second at batch size 500.

---

### D4: `Search Index Data Contributor` role requirement

**Decision:** Document that the dev identity needs `Search Index Data Contributor`
(not just `Data Reader`) to write documents.

**Rationale:** `Data Reader` only allows queries. Seeding requires write access.
The existing Function App MI already has `Data Contributor`; developers need it
assigned explicitly (one az role assignment command).

## Risks / Trade-offs

- **Synthetic chunks persist until `--delete` is run** → Document clearly; prefix
  makes accidental confusion with real data unlikely.

- **Index rebuild time** → After a large seed (100k+ chunks), the HNSW graph
  needs time to stabilise before queries reflect realistic latency. Allow 2-5
  minutes after seeding before running load tests.

- **Standard S1 storage limit (25GB/partition)** → At ~6KB per chunk (vector +
  metadata), 1 partition holds ~4M chunks. Well above any reasonable seed count.

- **Random vectors produce uniform QPS distribution** → Real production workloads
  have hot spots. Results are conservative (no cache warming on popular queries).
  This is acceptable — we want to measure the floor, not the ceiling.
