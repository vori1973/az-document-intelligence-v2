"""Unit tests for typed request/response/citation/execution/dependency-error
contracts (task 2.2 / 2.5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rag.contracts import (
    DependencyError,
    DependencyName,
    ExecutionMetadata,
    QueryCitation,
    QueryErrorResponse,
    QueryRequest,
    QueryResponse,
    QuestionValidationError,
)


def test_query_request_accepts_camel_case_json_body():
    request = QueryRequest.model_validate(
        {"question": "hi", "knowledgeGeneration": "17", "securityScope": "demo-public"}
    )
    assert request.question == "hi"
    assert request.knowledge_generation == "17"
    assert request.security_scope == "demo-public"


def test_query_request_defaults_are_safe():
    request = QueryRequest.model_validate({"question": "hi"})
    assert request.knowledge_generation is None
    assert request.security_scope is None


@pytest.mark.parametrize("field", ["onlyFigures", "topK", "history"])
def test_query_request_rejects_answer_affecting_fields_not_in_cache_identity(field):
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"question": "hi", field: True})


def test_query_request_requires_a_question():
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({})


def test_query_response_serializes_with_camel_case_aliases():
    response = QueryResponse(
        answer="The tire pressure is 32 psi.",
        citations=[QueryCitation(source_file="a.pdf", page=1, type="paragraph")],
        execution=ExecutionMetadata(
            backend_invocation_id="inv-1",
            correlation_id="corr-1",
            knowledge_generation="17",
            security_scope="demo-public",
            prompt_version="v1",
            logical_model_version="v1",
        ),
    )
    dumped = response.model_dump(by_alias=True)
    assert dumped["execution"]["backendInvocationId"] == "inv-1"
    assert dumped["execution"]["searchCalled"] is False
    assert dumped["citations"][0]["sourceFile"] == "a.pdf"


def test_query_error_response_carries_correlation_id():
    error = QueryErrorResponse(error="invalid_request", message="question is required", correlation_id="corr-1")
    dumped = error.model_dump(by_alias=True)
    assert dumped == {
        "error": "invalid_request",
        "message": "question is required",
        "correlationId": "corr-1",
    }


def test_question_validation_error_carries_a_machine_readable_reason():
    error = QuestionValidationError("empty", "question must not be empty")
    assert error.reason == "empty"
    assert str(error) == "question must not be empty"


def test_dependency_error_identifies_the_failed_dependency():
    cause = TimeoutError("timed out")
    error = DependencyError(DependencyName.SEARCH, "search timed out", cause=cause)
    assert error.dependency == DependencyName.SEARCH
    assert error.message == "search timed out"
    assert error.cause is cause
    assert "search dependency failed" in str(error)


def test_execution_metadata_defaults_to_not_called_and_no_tokens():
    execution = ExecutionMetadata(
        backend_invocation_id="inv-1",
        correlation_id="corr-1",
        knowledge_generation="0",
        security_scope="demo-public",
        prompt_version="v1",
        logical_model_version="v1",
    )
    assert execution.embedding_called is False
    assert execution.search_called is False
    assert execution.model_called is False
    assert execution.input_tokens is None
    assert execution.output_tokens is None
    assert execution.result_count == 0
