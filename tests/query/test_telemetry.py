"""Unit tests for structured, privacy-preserving telemetry (task 2.5)."""

from __future__ import annotations

import logging

import pytest

from rag.telemetry import (
    DISALLOWED_FIELDS,
    log_query_error,
    log_query_start,
    log_query_success,
)


def test_log_query_start_emits_expected_dimensions(caplog):
    with caplog.at_level(logging.INFO, logger="rag.query"):
        log_query_start(
            correlation_id="corr-1",
            backend_invocation_id="inv-1",
            cache_mode="none",
            knowledge_generation="17",
            security_scope="demo-public",
            prompt_version="v1",
            logical_model_version="v1",
        )
        record = caplog.records[-1]
        assert record.correlation_id == "corr-1"
        assert record.backend_invocation_id == "inv-1"
        assert record.knowledge_generation == "17"


def test_log_query_success_never_includes_raw_content(caplog):
    with caplog.at_level(logging.INFO, logger="rag.query"):
        log_query_success(
            correlation_id="corr-1",
            backend_invocation_id="inv-1",
            search_duration_ms=142.0,
            model_duration_ms=1284.0,
            input_tokens=2184,
            output_tokens=176,
            result_count=8,
        )
    record = caplog.records[-1]
    assert record.input_tokens == 2184
    assert record.result_count == 8
    for disallowed in DISALLOWED_FIELDS:
        assert not hasattr(record, disallowed)


def test_log_query_error_records_dependency_and_error_type(caplog):
    with caplog.at_level(logging.INFO, logger="rag.query"):
        log_query_error(
            correlation_id="corr-1",
            backend_invocation_id="inv-1",
            dependency="search",
            error_type="Timeout",
        )
    record = caplog.records[-1]
    assert record.dependency == "search"
    assert record.error_type == "Timeout"


@pytest.mark.parametrize("disallowed_field", sorted(DISALLOWED_FIELDS))
def test_emit_refuses_disallowed_fields(disallowed_field):
    """Defense in depth: even if a caller passes a disallowed field name by
    mistake, telemetry emission must refuse rather than silently leak it."""
    with pytest.raises(ValueError, match="disallowed telemetry field"):
        log_query_success(
            correlation_id="corr-1",
            backend_invocation_id="inv-1",
            **{disallowed_field: "sensitive value"},
        )


def test_disallowed_fields_cover_raw_content_and_secrets():
    assert "question" in DISALLOWED_FIELDS
    assert "prompt" in DISALLOWED_FIELDS
    assert "chunk_text" in DISALLOWED_FIELDS
    assert "access_token" in DISALLOWED_FIELDS
    assert "authorization" in DISALLOWED_FIELDS
    assert "user_id" in DISALLOWED_FIELDS
