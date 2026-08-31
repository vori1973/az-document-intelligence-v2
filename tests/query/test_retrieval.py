"""Unit tests for retrieval result mapping and hybrid search (task 2.5)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rag.contracts import RetrievedChunk
from rag.retrieval import (
    DEFAULT_SELECT,
    embed_text,
    hybrid_search,
    map_retrieved_chunk,
    map_retrieved_chunks,
)

RAW_HIT = {
    "id": "doc1-p3-para2",
    "type": "paragraph",
    "page": 3,
    "source_file": "technical-guide.pdf",
    "document_id": "abc123",
    "image_blob": None,
    "text_for_embedding": "The recommended tire pressure is 32 psi.",
    "@search.score": 0.91,
}


def test_map_retrieved_chunk_maps_all_fields():
    chunk = map_retrieved_chunk(RAW_HIT)
    assert isinstance(chunk, RetrievedChunk)
    assert chunk.id == "doc1-p3-para2"
    assert chunk.type == "paragraph"
    assert chunk.page == 3
    assert chunk.source_file == "technical-guide.pdf"
    assert chunk.document_id == "abc123"
    assert chunk.image_blob is None
    assert chunk.text_for_embedding == "The recommended tire pressure is 32 psi."
    assert chunk.score == 0.91


def test_map_retrieved_chunk_tolerates_missing_optional_fields():
    chunk = map_retrieved_chunk({"id": "x", "type": "figure", "page": 1, "source_file": "a.pdf"})
    assert chunk.document_id is None
    assert chunk.image_blob is None
    assert chunk.text_for_embedding == ""
    assert chunk.score is None


def test_map_retrieved_chunks_maps_a_list():
    chunks = map_retrieved_chunks([RAW_HIT, RAW_HIT])
    assert len(chunks) == 2
    assert all(isinstance(c, RetrievedChunk) for c in chunks)


def test_embed_text_returns_embedding_vector():
    client = MagicMock()
    client.embeddings.create.return_value.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    result = embed_text(client, "text-embedding-ada-002", "What is the tire pressure?")

    assert result == [0.1, 0.2, 0.3]
    client.embeddings.create.assert_called_once_with(
        model="text-embedding-ada-002", input=["What is the tire pressure?"]
    )


def test_embed_text_propagates_sdk_failures_unchanged():
    """`scripts/demo.py` relies on this raising the original exception type,
    not a wrapped one — see `rag.service` for the Function App's own
    translation into `DependencyError`."""
    client = MagicMock()
    client.embeddings.create.side_effect = RuntimeError("boom")

    try:
        embed_text(client, "text-embedding-ada-002", "question")
        assert False, "expected RuntimeError to propagate"
    except RuntimeError as exc:
        assert str(exc) == "boom"


@patch("rag.retrieval.requests.post")
def test_hybrid_search_includes_search_text_when_provided(mock_post):
    mock_post.return_value.json.return_value = {"value": [RAW_HIT]}
    mock_post.return_value.raise_for_status.return_value = None

    hits = hybrid_search(
        "https://search.example.net",
        "document-chunks",
        {"Authorization": "Bearer token"},
        [0.1, 0.2],
        search_text="tire pressure",
        k=5,
    )

    assert hits == [RAW_HIT]
    called_url, called_kwargs = mock_post.call_args
    assert called_url[0] == (
        "https://search.example.net/indexes/document-chunks/docs/search?api-version=2024-07-01"
    )
    body = called_kwargs["json"]
    assert body["search"] == "tire pressure"
    assert body["top"] == 5
    assert body["select"] == DEFAULT_SELECT
    assert body["vectorQueries"] == [
        {"kind": "vector", "vector": [0.1, 0.2], "fields": "embedding", "k": 5}
    ]
    assert "filter" not in body


@patch("rag.retrieval.requests.post")
def test_hybrid_search_omits_search_text_for_vector_only_mode(mock_post):
    mock_post.return_value.json.return_value = {"value": []}
    mock_post.return_value.raise_for_status.return_value = None

    hybrid_search(
        "https://search.example.net", "document-chunks", {}, [0.1], search_text=None, k=5
    )

    body = mock_post.call_args.kwargs["json"]
    assert "search" not in body


@patch("rag.retrieval.requests.post")
def test_hybrid_search_adds_figure_filter_when_only_figures(mock_post):
    mock_post.return_value.json.return_value = {"value": []}
    mock_post.return_value.raise_for_status.return_value = None

    hybrid_search(
        "https://search.example.net",
        "document-chunks",
        {},
        [0.1],
        search_text="q",
        only_figures=True,
    )

    body = mock_post.call_args.kwargs["json"]
    assert body["filter"] == "type eq 'figure'"


@patch("rag.retrieval.requests.post")
def test_hybrid_search_propagates_http_errors_unchanged(mock_post):
    class FakeHttpError(Exception):
        pass

    mock_post.return_value.raise_for_status.side_effect = FakeHttpError("service unavailable")

    try:
        hybrid_search("https://search.example.net", "document-chunks", {}, [0.1], search_text="q")
        assert False, "expected FakeHttpError to propagate"
    except FakeHttpError as exc:
        assert "service unavailable" in str(exc)
