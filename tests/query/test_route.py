"""Unit tests for the internal HTTP query route (task 3.4): successful
grounded queries, invalid payloads, dependency failures, caller-header
replacement expectations, and response metadata."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import azure.functions as func

from rag.answer import AnswerResult
from rag.config import QueryConfig
from rag.contracts import DependencyError, DependencyName
from rag.headers import (
    HEADER_BACKEND_INVOCATION_ID,
    HEADER_CORRELATION_ID,
    HEADER_INPUT_TOKENS,
    HEADER_KNOWLEDGE_GENERATION,
    HEADER_MODEL_CALLED,
    HEADER_OUTPUT_TOKENS,
    HEADER_SEARCH_CALLED,
    HEADER_SERVER_TIMING,
)
from rag.route import handle_query_request

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
        default_knowledge_generation="0",
        default_security_scope="demo-public",
        default_prompt_version="v1",
        default_logical_model_version="v1",
    )


def _request(body: dict | bytes, headers: dict | None = None) -> func.HttpRequest:
    raw_body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return func.HttpRequest(
        method="POST",
        url="/api/internal/query",
        headers=headers or {},
        body=raw_body,
    )


def _patched_dependencies():
    """Patch every real Azure dependency at the lowest level so `run_query`
    runs for real (exercising `rag.route` end to end) without any network
    call."""
    return (
        patch("rag.route.get_credential", return_value=MagicMock()),
        patch("rag.service.build_aoai_client", return_value=MagicMock()),
        patch("rag.service.build_search_headers", return_value={}),
        patch("rag.service.embed_text", return_value=[0.1, 0.2]),
        patch("rag.service.hybrid_search", return_value=HITS),
        patch(
            "rag.service.generate_answer",
            return_value=AnswerResult(text="The tire pressure is 32 psi. [1]", input_tokens=120, output_tokens=18),
        ),
    )


def test_successful_grounded_query_returns_200_with_answer_and_citations():
    patches = _patched_dependencies()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        response = handle_query_request(_request({"question": "What is the tire pressure?"}), config=_config())

    assert response.status_code == 200
    payload = json.loads(response.get_body())
    assert payload["answer"] == "The tire pressure is 32 psi. [1]"
    assert len(payload["citations"]) == 1
    assert payload["citations"][0]["sourceFile"] == "technical-guide.pdf"
    assert payload["execution"]["searchCalled"] is True
    assert payload["execution"]["modelCalled"] is True


def test_successful_query_sets_execution_and_server_timing_headers():
    patches = _patched_dependencies()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        response = handle_query_request(_request({"question": "What is the tire pressure?"}), config=_config())

    assert response.headers[HEADER_BACKEND_INVOCATION_ID]
    assert response.headers[HEADER_CORRELATION_ID]
    assert response.headers[HEADER_SEARCH_CALLED] == "true"
    assert response.headers[HEADER_MODEL_CALLED] == "true"
    assert response.headers[HEADER_INPUT_TOKENS] == "120"
    assert response.headers[HEADER_OUTPUT_TOKENS] == "18"
    assert "search;dur=" in response.headers[HEADER_SERVER_TIMING]
    assert "model;dur=" in response.headers[HEADER_SERVER_TIMING]


def test_invalid_json_body_returns_400():
    with patch("rag.route.get_credential", return_value=MagicMock()):
        response = handle_query_request(_request(b"not json"), config=_config())

    assert response.status_code == 400
    payload = json.loads(response.get_body())
    assert payload["error"] == "invalid_json"
    assert response.headers[HEADER_CORRELATION_ID]


def test_missing_question_field_returns_400():
    with patch("rag.route.get_credential", return_value=MagicMock()):
        response = handle_query_request(_request({}), config=_config())

    assert response.status_code == 400
    payload = json.loads(response.get_body())
    assert payload["error"] == "invalid_request"


def test_empty_question_returns_400_without_invoking_dependencies():
    embed_mock = MagicMock()
    with patch("rag.route.get_credential", return_value=MagicMock()), patch(
        "rag.service.embed_text", embed_mock
    ):
        response = handle_query_request(_request({"question": "   "}), config=_config())

    assert response.status_code == 400
    payload = json.loads(response.get_body())
    assert payload["error"] == "empty"
    embed_mock.assert_not_called()


def test_dependency_failure_returns_502_with_correlation_id():
    with patch("rag.route.get_credential", return_value=MagicMock()), patch(
        "rag.service.build_aoai_client", return_value=MagicMock()
    ), patch("rag.service.build_search_headers", return_value={}), patch(
        "rag.service.embed_text",
        side_effect=DependencyError(DependencyName.EMBEDDING, "embedding endpoint unreachable"),
    ):
        response = handle_query_request(
            _request({"question": "What is the tire pressure?"}, headers={HEADER_CORRELATION_ID: "corr-xyz"}),
            config=_config(),
        )

    assert response.status_code == 502
    payload = json.loads(response.get_body())
    assert payload["error"] == "embedding_unavailable"
    assert payload["correlationId"] == "corr-xyz"
    assert response.headers[HEADER_CORRELATION_ID] == "corr-xyz"


def test_dependency_failure_does_not_return_a_partial_success_body():
    """Spec scenario: 'Dependency failure' — a non-success response must
    never look like a successful (and therefore cacheable) answer."""
    with patch("rag.route.get_credential", return_value=MagicMock()), patch(
        "rag.service.build_aoai_client", return_value=MagicMock()
    ), patch("rag.service.build_search_headers", return_value={}), patch(
        "rag.service.embed_text", return_value=[0.1]
    ), patch(
        "rag.service.hybrid_search",
        side_effect=DependencyError(DependencyName.SEARCH, "search timeout"),
    ):
        response = handle_query_request(_request({"question": "q"}), config=_config())

    assert response.status_code == 502
    payload = json.loads(response.get_body())
    assert "answer" not in payload
    assert "citations" not in payload


def test_caller_supplied_generation_is_replaced_by_trusted_header():
    """Spec scenario: 'Caller supplies cache partition values' — the backend
    must use the trusted header value, not a caller-supplied body value, for
    the reported knowledge generation."""
    patches = _patched_dependencies()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        response = handle_query_request(
            _request(
                {"question": "What is the tire pressure?", "knowledgeGeneration": "999-caller-supplied"},
                headers={HEADER_KNOWLEDGE_GENERATION: "17"},
            ),
            config=_config(),
        )

    payload = json.loads(response.get_body())
    assert payload["execution"]["knowledgeGeneration"] == "17"
    assert response.headers[HEADER_KNOWLEDGE_GENERATION] == "17"


def test_caller_supplied_generation_falls_back_to_config_default_when_no_trusted_header():
    """When APIM's trusted header is absent (local development / direct
    testing), the backend falls back to its own non-secret config default —
    never to a caller-supplied body value."""
    patches = _patched_dependencies()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        response = handle_query_request(
            _request({"question": "What is the tire pressure?", "knowledgeGeneration": "999-caller-supplied"}),
            config=_config(),
        )

    payload = json.loads(response.get_body())
    assert payload["execution"]["knowledgeGeneration"] == "0"


def test_direct_dependency_failure_uses_same_correlation_id_in_response_and_telemetry():
    with patch("rag.route.get_credential", return_value=MagicMock()), patch(
        "rag.service.build_aoai_client", return_value=MagicMock()
    ), patch("rag.service.build_search_headers", return_value={}), patch(
        "rag.service.embed_text", side_effect=RuntimeError("embedding down")
    ), patch("rag.service.log_query_error") as log_error:
        response = handle_query_request(
            _request({"question": "What is the tire pressure?"}),
            config=_config(),
        )

    payload = json.loads(response.get_body())
    assert response.status_code == 502
    assert payload["correlationId"] == log_error.call_args.kwargs["correlation_id"]
