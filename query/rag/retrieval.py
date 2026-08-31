"""
Query embedding, hybrid retrieval, and result mapping (task 2.1 / 2.5).

`embed_text` and `hybrid_search` are extracted unchanged in behavior from
`scripts/demo.py`'s `_embed`/`_retrieve` (task 2.1): same request shape, same
default `select` fields, same timeout, and the same exceptions propagate
on failure (`scripts/demo.py` calls these functions directly and its CLI
behavior on a dependency failure must not change). `rag.service` — used only
by the Function App — is responsible for translating a failure here into a
`DependencyError` for the HTTP route.
"""

from __future__ import annotations

import requests
from openai import AzureOpenAI

from .contracts import RetrievedChunk

DEFAULT_SELECT = "id,type,page,source_file,image_blob,text_for_embedding,document_id"


def embed_text(client: AzureOpenAI, model: str, text: str) -> list[float]:
    """Generate a query embedding."""
    return client.embeddings.create(model=model, input=[text]).data[0].embedding


def hybrid_search(
    search_endpoint: str,
    index_name: str,
    headers: dict,
    embedding: list[float],
    *,
    search_text: str | None = None,
    k: int = 8,
    only_figures: bool = False,
    select: str = DEFAULT_SELECT,
    api_version: str = "2024-07-01",
    timeout: int = 60,
) -> list[dict]:
    """Hybrid (or vector-only, when `search_text` is None) retrieval.

    The index has no server-side vectorizer, so the query vector is computed
    by the caller (`embed_text`) and passed explicitly — see
    `add-query-time-vectorizer` for the pending alternative. Propagates
    `requests` exceptions on failure unchanged, matching
    `scripts/demo.py`'s `_retrieve`/`_vector_scores`.
    """
    body: dict = {
        "top": k,
        "select": select,
        "vectorQueries": [{"kind": "vector", "vector": embedding, "fields": "embedding", "k": k}],
    }
    if search_text is not None:
        body["search"] = search_text
    if only_figures:
        body["filter"] = "type eq 'figure'"

    response = requests.post(
        f"{search_endpoint}/indexes/{index_name}/docs/search?api-version={api_version}",
        headers=headers,
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("value", [])


def map_retrieved_chunk(raw: dict) -> RetrievedChunk:
    """Pure mapping from one raw Search hit to a typed `RetrievedChunk`
    (task 2.1 / 2.5). Never raises on missing optional fields."""
    return RetrievedChunk(
        id=raw.get("id", ""),
        type=raw.get("type", ""),
        page=raw.get("page", 0),
        source_file=raw.get("source_file", ""),
        document_id=raw.get("document_id"),
        image_blob=raw.get("image_blob"),
        text_for_embedding=raw.get("text_for_embedding") or "",
        score=raw.get("@search.score"),
    )


def map_retrieved_chunks(raw_hits: list[dict]) -> list[RetrievedChunk]:
    return [map_retrieved_chunk(hit) for hit in raw_hits]
