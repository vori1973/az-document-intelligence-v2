# Azure AI Search — Optimization Recommendations

Findings based on load testing of binary-quantized production indexes.
All uncompressed (float32) indexes are excluded from this test scope —
compression migration is a separate workstream.

---

## Background — root cause hypothesis

The current configuration (k=50, `rerankWithOriginalVectors: true`, ~15.6 GB float32
store) is consistent with a pattern where retrieval accuracy was low and each setting
was added to compensate. The likely chain:

```
Poor table extraction from PDFs
        │
        ▼
Garbled chunks — tables stored as raw pipe-separated text with no semantic structure
        │
        ▼
Poor embeddings — the model sees noise, not meaning; relevant chunks rank low
        │
        ▼
Low accuracy at default k=4 — right answer not in top results
        │
        ▼
k increased to 50 — wider candidate net hoping the answer appears somewhere
        │
        ▼
rerankWithOriginalVectors: true — exact float32 scoring to improve ordering of 50 candidates
        │
        ▼
stored: true on embeddings — required to support float32 reranking
        │
        ▼
~15.6 GB float32 store + slow queries ← current state
```

**The critical point:** float32 reranking corrects ordering errors introduced by binary
compression. It cannot fix a chunk that was never semantically meaningful. If the
embedding of a garbled table is poor, exact cosine similarity still scores it poorly —
it just does so more precisely. The machinery is working correctly; it is working on
bad input.

If chunking is fixed, the chain collapses:

```
Prose-normalised table chunk
"Implant size 1 is available in widths 52mm, 54mm, 56mm."
        │
        ▼
Good embedding — semantically matches "implant size for 54mm femur"
        │
        ▼
Relevant chunk surfaces at k=10 naturally
        │
        ▼
rerankWithOriginalVectors: true — less critical, binary errors rarely
                                   affect top results at this scale
        │
        ▼
stored: false — safe, 26× storage saving, no accuracy trade-off
```

---

## Information requested from customer

Before implementing Findings 3 and 4, please provide:

**1. Sample documents**
2–3 PDF files where search accuracy is low. Medical device documents with
specification tables, sizing charts, or comparison matrices are most useful.

**2. Sample chunks from those documents**
The raw extracted text as it appears in the index — not the original PDF.
Specifically chunks that contain or should contain table data. This is the
fastest way to confirm whether table normalisation is the root cause.

**3. Sample low-accuracy queries**
2–3 queries where the expected answer was not returned or ranked poorly.
Include what the correct answer should have been and which document it came from.

**4. Document processing pipeline**
Which tool is used to extract text from PDFs before chunking:
- Azure Document Intelligence (and which model — prebuilt-read, prebuilt-layout, or custom)
- PyMuPDF / PDFplumber / pdfminer
- Other

Azure Document Intelligence with the `prebuilt-layout` model preserves table
structure as markdown. Raw PDF text extractors typically do not — they read
left-to-right across columns producing word salad.

**5. Current `rerankWithOriginalVectors` value**
Confirm whether this is `true` or `false` in the index compression config.
This determines whether the float32 document store is actively used for
reranking or is stored without serving a purpose.

---

## Index inventory (binary quantized, in scope)

| Index | Chunks | Vector index | Bytes/chunk | Config |
|---|---|---|---|---|
| aiadvisor-all-text-large3 | 34,921 | 14.63 MB | 439 | binary quantized |
| aiadvisor-prod-index-ee | 345,360 | 171.79 MB | 522 | binary quantized |
| aiadvisor-prod-index-ep | 446,523 | 222.34 MB | 522 | binary quantized |
| aiadvisor-prod-index-hr | 40,039 | 17.11 MB | 448 | binary quantized |
| aiadvisor-prod-index-tr | 242,562 | 102.34 MB | 442 | binary quantized |
| aiadvisor-prod-index-wc | 103,431 | 43.42 MB | 440 | binary quantized |
| aiadvisor-prod | 62,121 | 26.02 MB | 439 | binary quantized |

**Key finding:** binary quantization reduces HNSW traversal to ~500 bytes/node — traversal
is no longer the bottleneck. With `rerankWithOriginalVectors: true` (standard config), the
service loads the original float32 vectors for every candidate after traversal. This
float32 reranking step scales directly with `k × oversampling` and is the primary
cost driver at the current settings.

```
k=50, oversampling=4  →  200 candidates × 12,288 bytes (float32)  =  ~2.4 MB loaded per query
k=10, oversampling=4  →   40 candidates × 12,288 bytes (float32)  =  ~490 KB loaded per query
                                                                        ↑ 5× cheaper
```

---

## Finding 1 — `embeddings` field is Retrievable   ★ ZERO-RISK · NO REINDEX

The vector field (`embeddings`, 3072 dims) is marked Retrievable. Unless `$select` excludes
it, every search response serialises 3,072 floats per result document:

```
k=50  ×  3,072 floats  ×  ~9 chars JSON  =  ~1.4 MB per query response
k=10  ×  3,072 floats  ×  ~9 chars JSON  =  ~280 KB per query response
```

This inflates response size and increases serialisation CPU on the search service.
The application never uses the vector values — they are embedded and discarded on the
client side.

**Fix — add `$select` to all search calls:**

```python
results = client.search(
    search_text=query_text,
    vector_queries=[...],
    select=[
        "child_chunk_content",
        "parent_chunk_content",
        "DocumentTitle",
        "FileName",
        "ProductGroup",
        "Location",
    ]
    # embeddings excluded — never needed in response
)
```

No index change. No reindex. Takes effect on the next deploy.

> **Keep `retrievable: true` only if** the application uses the returned vectors for
> client-side re-ranking, semantic caching, or near-duplicate suppression. In a standard
> RAG pipeline none of these apply — the vector is used inside the HNSW graph and never
> needed in the response.

---

## Finding 2 — BM25 runs across all searchable fields   ★ ZERO-RISK · NO REINDEX

The index has 3 large text fields with English analyzers (`child_chunk_content`,
`parent_chunk_content`, `page_content`) plus ~8 searchable metadata string fields
(`ProductGroup`, `ProductCategory`, `Location`, `DocumentTitle`, `FileName`, etc.).

Without `searchFields`, a hybrid query scores BM25 across all of them simultaneously.
The parent-child chunking pattern means `child_chunk_content` is the field relevant for
keyword matching — the others add noise and CPU cost with no quality benefit.

**Fix — specify `searchFields` on every hybrid query:**

```python
results = client.search(
    search_text=query_text,
    search_fields=["child_chunk_content"],   # BM25 on content only
    vector_queries=[...],
)
```

For LangChain `AzureSearch` retriever:

```python
retriever = vector_store.as_retriever(
    search_type="hybrid",
    search_kwargs={
        "k": 10,
        "search_fields": ["child_chunk_content"],
    }
)
```

No index change. No reindex. Takes effect on the next deploy.

---

## Finding 3 — k=50 drives float32 reranking cost   CODE CHANGE · NO REINDEX

With binary quantization and `rerankWithOriginalVectors: true`, HNSW traversal is cheap
(~500 bytes/node). The float32 reranking step that follows is the bottleneck — it loads
the original float32 vectors for every candidate in `k × oversampling`.

At k=50, oversampling=4: the service loads 200 float32 vectors (~2.4 MB) on every query.
The RAG chain consumes 3–5 results. The other 45–47 retrieved candidates are reranked
and discarded.

```
k value   oversampling   Internal candidates   Float32 rerank load
─────────────────────────────────────────────────────────────────
k=50          4               200                  ~2.4 MB / query   ← current
k=10          4                40                  ~490 KB / query   ← recommended
k=4           4                16                  ~196 KB / query   ← LangChain default
```

**Fix — reduce k in LangChain retriever:**

```python
# Before (common override — expensive on large indexes)
retriever = vector_store.as_retriever(search_kwargs={"k": 50})

# After (recommended starting point)
retriever = vector_store.as_retriever(search_kwargs={"k": 10})
```

**Expected impact against the current load test results:**

| Concurrent users | Current avg (ms) | Expected after k=10 |
|---|---|---|
| 1 | 4,709 | ~800–1,200 |
| 5 | 10,458 | ~1,500–2,500 |
| 10 | 28,261 | ~3,000–5,000 |
| 20 | 37,353 | ~6,000–10,000 |

Saturation knee should move from ~5 concurrent to ~25–40 concurrent at 2 replicas.
Re-run the same concurrency ladder after this change before adjusting infrastructure.

**If latency at 1 user remains above 2 seconds after k=10**, reduce oversampling:

```json
"compressions": [{
  "name": "binary-compression",
  "kind": "binaryQuantization",
  "rerankWithOriginalVectors": true,
  "defaultOversampling": 2
}]
```

`oversampling=2` halves the float32 reranking load again. Test recall quality on a
representative query sample before committing — oversampling below 4 can reduce
result accuracy on selective post-filters.

---

## Finding 4 — Set `stored: false` on the `embeddings` field   REINDEX REQUIRED

Apply only after Findings 1–3 are in place and re-tested, and after chunk quality
is confirmed (see the PDF sample request). Requires recreating the index but has
permanent storage and query cost reduction.

Finding 1 (`$select`) is a query-time workaround — the float32 vectors are still
stored and consuming ~15.6 GB, they are just excluded from responses. Setting
`stored: false` is the permanent fix: if the application never retrieves the vectors,
there is no reason to store them. `retrievable` and `stored` should always be set
together — `retrievable: true` is only valid when `stored: true`.

With binary quantization + `rerankWithOriginalVectors: true`, Azure Search stores
two copies of every vector:

```
Binary HNSW graph      ~500 bytes/chunk   used for traversal
Float32 document store  12,288 bytes/chunk  loaded per candidate for reranking
```

Setting `stored: false` removes the float32 copy from the document store entirely.

```json
{
  "name": "embeddings",
  "type": "Collection(Edm.Single)",
  "searchable": true,
  "retrievable": false,
  "stored": false,
  "dimensions": 3072,
  "vectorSearchProfile": "hnsw-binary"
}
```

Also set `rerankWithOriginalVectors: false` in the compression config — with no
float32 data in the document store, leaving this as `true` produces undefined
fallback behaviour.

**Storage savings across in-scope indexes:**

| Index | Chunks | Float32 store (current) | After stored=false |
|---|---|---|---|
| aiadvisor-prod-index-ep | 446,523 | ~5.5 GB | ~222 MB (binary only) |
| aiadvisor-prod-index-ee | 345,360 | ~4.2 GB | ~172 MB |
| aiadvisor-prod-index-tr | 242,562 | ~2.9 GB | ~102 MB |
| aiadvisor-prod-index-wc | 103,431 | ~1.3 GB | ~43 MB |
| aiadvisor-prod | 62,121 | ~763 MB | ~26 MB |
| aiadvisor-prod-index-hr | 40,039 | ~492 MB | ~17 MB |
| aiadvisor-all-text-large3 | 34,921 | ~429 MB | ~15 MB |
| **Total** | **1.27M** | **~15.6 GB** | **~597 MB** |

**~26× storage reduction.** At S1 (25 GB/partition) this may allow a partition
to be removed, directly reducing monthly cost.

**Query performance impact:** eliminates the float32 reranking IO entirely —
the same bottleneck Finding 3 reduces by lowering k. After k=10 is validated,
this removes the remaining reranking cost.

**Trade-off:** without float32 reranking, binary quantization approximation errors
are not corrected. Recall typically drops 2–5% vs float32-reranked results.
Run a representative query sample comparing both configurations before committing.
Bundle this reindex with any other schema changes to avoid doing it twice.

---

## Priority summary

```
Action                                  Impact    Effort    Reindex
──────────────────────────────────────────────────────────────────
Add $select (exclude embeddings)        High      Low       No      ← do first
Add searchFields=child_chunk_content    High      Low       No      ← do first
Reduce k from 50 to 10                 High      Low       No
stored:false on embeddings field        High      Medium    Yes     ← after k validated
```

Apply Findings 1 and 2 immediately — zero-risk, no reindex, take effect on next
deploy. Reduce k (Finding 3) and re-run the full concurrency ladder. Only then
schedule the reindex for Finding 4 once chunk quality is confirmed and k is stable.
