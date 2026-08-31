"""Unit tests for trusted context headers, correlation, and Server-Timing
(task 2.4 / 2.5)."""

from __future__ import annotations

from rag.config import QueryConfig
from rag.contracts import ExecutionMetadata
from rag.headers import (
    HEADER_BACKEND_INVOCATION_ID,
    HEADER_CACHE_MODE,
    HEADER_CORRELATION_ID,
    HEADER_EMBEDDING_CALLED,
    HEADER_KNOWLEDGE_GENERATION,
    HEADER_MODEL_CALLED,
    HEADER_MODEL_VERSION,
    HEADER_OUTPUT_TOKENS,
    HEADER_PROMPT_VERSION,
    HEADER_SEARCH_CALLED,
    HEADER_SECURITY_SCOPE,
    HEADER_SERVER_TIMING,
    build_server_timing,
    execution_response_headers,
    resolve_trusted_context,
)


def _config(**overrides) -> QueryConfig:
    base = dict(
        search_endpoint="https://search.example.net",
        search_index="document-chunks",
        aoai_endpoint="https://aoai.example.net/",
        chat_model="gpt-4o-mini",
        embed_model="text-embedding-ada-002",
    )
    base.update(overrides)
    return QueryConfig(**base)


def test_resolve_trusted_context_uses_apim_headers_when_present():
    config = _config()
    headers = {
        HEADER_KNOWLEDGE_GENERATION: "17",
        HEADER_SECURITY_SCOPE: "demo-public",
        HEADER_PROMPT_VERSION: "v2",
        HEADER_MODEL_VERSION: "v3",
        HEADER_CACHE_MODE: "apim-built-in",
        HEADER_CORRELATION_ID: "corr-abc",
    }
    trusted = resolve_trusted_context(headers, config)
    assert trusted.knowledge_generation == "17"
    assert trusted.security_scope == "demo-public"
    assert trusted.prompt_version == "v2"
    assert trusted.logical_model_version == "v3"
    assert trusted.cache_mode == "apim-built-in"
    assert trusted.correlation_id == "corr-abc"


def test_resolve_trusted_context_falls_back_to_config_defaults_when_headers_absent():
    config = _config(
        default_knowledge_generation="0",
        default_security_scope="demo-public",
        default_prompt_version="v1",
        default_logical_model_version="v1",
    )
    trusted = resolve_trusted_context({}, config)
    assert trusted.knowledge_generation == "0"
    assert trusted.security_scope == "demo-public"
    assert trusted.prompt_version == "v1"
    assert trusted.logical_model_version == "v1"
    assert trusted.cache_mode == "none"
    assert trusted.correlation_id  # a correlation id is always generated


def test_resolve_trusted_context_header_lookup_is_case_insensitive():
    config = _config()
    headers = {"x-demo-generation": "42"}
    trusted = resolve_trusted_context(headers, config)
    assert trusted.knowledge_generation == "42"


def test_resolve_trusted_context_generates_a_correlation_id_when_absent():
    config = _config()
    first = resolve_trusted_context({}, config)
    second = resolve_trusted_context({}, config)
    assert first.correlation_id != second.correlation_id


def test_build_server_timing_formats_named_durations():
    value = build_server_timing(("embedding", 12.34), ("search", 142.0), ("model", 1284.5))
    assert value == "embedding;dur=12.3, search;dur=142.0, model;dur=1284.5"


def test_build_server_timing_omits_entries_with_no_duration():
    value = build_server_timing(("embedding", None), ("search", 142.0))
    assert value == "search;dur=142.0"


def _execution(**overrides) -> ExecutionMetadata:
    base = dict(
        backend_invocation_id="inv-1",
        correlation_id="corr-1",
        knowledge_generation="17",
        security_scope="demo-public",
        prompt_version="v1",
        logical_model_version="v1",
        cache_mode="none",
        embedding_called=True,
        embedding_duration_ms=12.0,
        search_called=True,
        search_duration_ms=142.0,
        model_called=True,
        model_duration_ms=1284.0,
        input_tokens=2184,
        output_tokens=176,
        result_count=8,
    )
    base.update(overrides)
    return ExecutionMetadata(**base)


def test_execution_response_headers_reports_dependency_and_correlation_metadata():
    headers = execution_response_headers(_execution())
    assert headers[HEADER_BACKEND_INVOCATION_ID] == "inv-1"
    assert headers[HEADER_CORRELATION_ID] == "corr-1"
    assert headers[HEADER_KNOWLEDGE_GENERATION] == "17"
    assert headers[HEADER_EMBEDDING_CALLED] == "true"
    assert headers[HEADER_SEARCH_CALLED] == "true"
    assert headers[HEADER_MODEL_CALLED] == "true"
    assert headers[HEADER_OUTPUT_TOKENS] == "176"
    assert "embedding;dur=" in headers[HEADER_SERVER_TIMING]


def test_execution_response_headers_omit_absent_token_counts():
    execution = _execution(input_tokens=None, output_tokens=None)
    headers = execution_response_headers(execution)
    from rag.headers import HEADER_INPUT_TOKENS

    assert HEADER_INPUT_TOKENS not in headers
    assert HEADER_OUTPUT_TOKENS not in headers


def test_execution_response_headers_reflect_cache_hit_as_no_dependencies_called():
    """Spec scenario: 'Cache-hit proof' — a cache hit must not report new
    embedding/Search/model invocations."""
    execution = _execution(
        embedding_called=False,
        embedding_duration_ms=None,
        search_called=False,
        search_duration_ms=None,
        model_called=False,
        model_duration_ms=None,
        input_tokens=None,
        output_tokens=None,
        cache_mode="apim-built-in",
    )
    headers = execution_response_headers(execution)
    assert headers[HEADER_EMBEDDING_CALLED] == "false"
    assert headers[HEADER_SEARCH_CALLED] == "false"
    assert headers[HEADER_MODEL_CALLED] == "false"
    assert HEADER_SERVER_TIMING not in headers
