"""Unit tests for the query service orchestration (task 2.5): grounded
response shape, dependency failures, and telemetry correlation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rag.answer import AnswerResult
from rag.config import QueryConfig
from rag.contracts import (
    DependencyError,
    DependencyName,
    QueryRequest,
    QueryResponse,
    QuestionValidationError,
)
from rag.headers import HEADER_CORRELATION_ID, HEADER_KNOWLEDGE_GENERATION
from rag.service import run_query

HITS = [
    {
        "id": "doc1-p3-para2",
        "type": "paragraph",
        "page": 3,
        "source_file": "technical-guide.pdf",
        "text_for_embedding": "The recommended tire pressure is 32 psi.",
        "image_blob": None,
        "@search.score": 0.91,
    }
]


def _config() -> QueryConfig:
    return QueryConfig(
        search_endpoint="https://search.example.net",
        search_index="document-chunks",
        aoai_endpoint="https://aoai.example.net/",
        chat_model="gpt-4o-mini",
        embed_model="text-embedding-ada-002",
        default_knowledge_generation="17",
        default_security_scope="demo-public",
        default_prompt_version="v1",
        default_logical_model_version="v1",
    )


@patch("rag.service.generate_answer")
@patch("rag.service.hybrid_search")
@patch("rag.service.embed_text")
@patch("rag.service.build_search_headers")
@patch("rag.service.build_aoai_client")
def test_run_query_returns_grounded_response_with_execution_metadata(
    mock_build_aoai, mock_build_search_headers, mock_embed, mock_hybrid_search, mock_generate_answer
):
    mock_build_aoai.return_value = MagicMock()
    mock_build_search_headers.return_value = {"Authorization": "Bearer token"}
    mock_embed.return_value = [0.1, 0.2, 0.3]
    mock_hybrid_search.return_value = HITS
    mock_generate_answer.return_value = AnswerResult(
        text="The tire pressure is 32 psi. [1]", input_tokens=120, output_tokens=18
    )

    request = QueryRequest(question="What is the tire pressure?")
    response = run_query(request, {}, config=_config(), credential=MagicMock())

    assert isinstance(response, QueryResponse)
    assert response.answer == "The tire pressure is 32 psi. [1]"
    assert len(response.citations) == 1
    assert response.citations[0].source_file == "technical-guide.pdf"

    execution = response.execution
    assert execution.embedding_called is True
    assert execution.search_called is True
    assert execution.model_called is True
    assert execution.input_tokens == 120
    assert execution.output_tokens == 18
    assert execution.result_count == 1
    assert execution.knowledge_generation == "17"
    assert execution.security_scope == "demo-public"
    assert execution.backend_invocation_id  # non-empty, generated
    assert execution.correlation_id  # non-empty, generated


@patch("rag.service.build_search_headers")
@patch("rag.service.build_aoai_client")
def test_run_query_uses_trusted_headers_over_config_defaults(mock_build_aoai, mock_build_search_headers):
    mock_build_aoai.return_value = MagicMock()
    mock_build_search_headers.return_value = {}

    with patch("rag.service.embed_text", return_value=[0.1]), patch(
        "rag.service.hybrid_search", return_value=HITS
    ), patch(
        "rag.service.generate_answer",
        return_value=AnswerResult(text="answer", input_tokens=1, output_tokens=1),
    ):
        request = QueryRequest(question="q")
        response = run_query(
            request,
            {HEADER_KNOWLEDGE_GENERATION: "42", HEADER_CORRELATION_ID: "trusted-corr"},
            config=_config(),
            credential=MagicMock(),
        )

    assert response.execution.knowledge_generation == "42"
    assert response.execution.correlation_id == "trusted-corr"


def test_run_query_rejects_invalid_question_before_any_dependency_call():
    request = QueryRequest(question="   ")
    with pytest.raises(QuestionValidationError):
        run_query(request, {}, config=_config(), credential=MagicMock())


@patch("rag.service.build_search_headers")
@patch("rag.service.build_aoai_client")
def test_run_query_wraps_embedding_failure_as_dependency_error(mock_build_aoai, mock_build_search_headers):
    mock_build_aoai.return_value = MagicMock()
    mock_build_search_headers.return_value = {}

    with patch("rag.service.embed_text", side_effect=RuntimeError("embedding down")):
        request = QueryRequest(question="What is the tire pressure?")
        with pytest.raises(DependencyError) as exc_info:
            run_query(request, {}, config=_config(), credential=MagicMock())

    assert exc_info.value.dependency == DependencyName.EMBEDDING


@patch("rag.service.build_search_headers")
@patch("rag.service.build_aoai_client")
def test_run_query_wraps_search_failure_as_dependency_error(mock_build_aoai, mock_build_search_headers):
    mock_build_aoai.return_value = MagicMock()
    mock_build_search_headers.return_value = {}

    with patch("rag.service.embed_text", return_value=[0.1]), patch(
        "rag.service.hybrid_search", side_effect=RuntimeError("search down")
    ):
        request = QueryRequest(question="What is the tire pressure?")
        with pytest.raises(DependencyError) as exc_info:
            run_query(request, {}, config=_config(), credential=MagicMock())

    assert exc_info.value.dependency == DependencyName.SEARCH


@patch("rag.service.build_search_headers")
@patch("rag.service.build_aoai_client")
def test_run_query_wraps_model_failure_as_dependency_error(mock_build_aoai, mock_build_search_headers):
    mock_build_aoai.return_value = MagicMock()
    mock_build_search_headers.return_value = {}

    with patch("rag.service.embed_text", return_value=[0.1]), patch(
        "rag.service.hybrid_search", return_value=HITS
    ), patch("rag.service.generate_answer", side_effect=RuntimeError("model down")):
        request = QueryRequest(question="What is the tire pressure?")
        with pytest.raises(DependencyError) as exc_info:
            run_query(request, {}, config=_config(), credential=MagicMock())

    assert exc_info.value.dependency == DependencyName.MODEL


@patch("rag.service.log_query_error")
@patch("rag.service.build_search_headers")
@patch("rag.service.build_aoai_client")
def test_run_query_logs_dependency_error_without_raw_content(
    mock_build_aoai, mock_build_search_headers, mock_log_error
):
    mock_build_aoai.return_value = MagicMock()
    mock_build_search_headers.return_value = {}

    with patch("rag.service.embed_text", side_effect=RuntimeError("embedding down")):
        request = QueryRequest(question="What is the tire pressure?")
        with pytest.raises(DependencyError):
            run_query(request, {}, config=_config(), credential=MagicMock())

    mock_log_error.assert_called_once()
    _, kwargs = mock_log_error.call_args
    assert kwargs["dependency"] == "embedding"
    assert "question" not in kwargs
