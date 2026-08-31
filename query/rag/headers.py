"""
Trusted APIM context headers, correlation, execution headers, and
Server-Timing (task 2.4 / 3.2).

APIM sets the `X-Demo-*` request headers below before forwarding to this
backend, replacing or stripping any caller-supplied values (see
`infra/policies/rag-api.xml` and
`openspec/changes/add-apim-exact-cache-demo/design.md`, "Keep APIM
operations as policy variants over one backend"). This module defines the
contract the backend trusts and echoes back; the gateway remains
authoritative for the current request.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

from .contracts import ExecutionMetadata

# Trusted request headers APIM is expected to set (task 3.2).
HEADER_KNOWLEDGE_GENERATION = "X-Demo-Generation"
HEADER_SECURITY_SCOPE = "X-Demo-Security-Scope"
HEADER_PROMPT_VERSION = "X-Demo-Prompt-Version"
HEADER_MODEL_VERSION = "X-Demo-Model-Version"
HEADER_CACHE_MODE = "X-Demo-Cache-Mode"
HEADER_CORRELATION_ID = "X-Demo-Correlation-Id"

# Execution/response headers this backend sets on every response.
HEADER_BACKEND_INVOCATION_ID = "X-Demo-Backend-Invocation-Id"
HEADER_EMBEDDING_CALLED = "X-Demo-Embedding-Called"
HEADER_SEARCH_CALLED = "X-Demo-Search-Called"
HEADER_MODEL_CALLED = "X-Demo-Model-Called"
HEADER_INPUT_TOKENS = "X-Demo-Input-Tokens"
HEADER_OUTPUT_TOKENS = "X-Demo-Output-Tokens"
HEADER_SERVER_TIMING = "Server-Timing"


@dataclass(frozen=True)
class TrustedContext:
    """The cache-partition dimensions and correlation id this backend will
    use for one request — resolved by `resolve_trusted_context`, never from
    the request body (task 2.2 / spec "Caller supplies cache partition
    values")."""

    knowledge_generation: str
    security_scope: str
    prompt_version: str
    logical_model_version: str
    cache_mode: str
    correlation_id: str


def resolve_trusted_context(headers: dict, config) -> TrustedContext:
    """Resolve trusted context from APIM's headers, falling back to
    non-secret config defaults when a header is absent (local development or
    direct testing) — case-insensitive header lookup, since HTTP header
    names are not case sensitive."""
    lower_headers = {k.lower(): v for k, v in headers.items()}

    def header(name: str, default: str) -> str:
        value = lower_headers.get(name.lower())
        return value if value else default

    correlation_id = header(HEADER_CORRELATION_ID, "") or uuid.uuid4().hex

    return TrustedContext(
        knowledge_generation=header(HEADER_KNOWLEDGE_GENERATION, config.default_knowledge_generation),
        security_scope=header(HEADER_SECURITY_SCOPE, config.default_security_scope),
        prompt_version=header(HEADER_PROMPT_VERSION, config.default_prompt_version),
        logical_model_version=header(HEADER_MODEL_VERSION, config.default_logical_model_version),
        cache_mode=header(HEADER_CACHE_MODE, "none"),
        correlation_id=correlation_id,
    )


def new_backend_invocation_id() -> str:
    return uuid.uuid4().hex


def build_server_timing(*durations_ms: tuple[str, Optional[float]]) -> str:
    """Build a `Server-Timing` header value, e.g.
    `embedding;dur=12.3, search;dur=142.0, model;dur=1284.5`. Entries with no
    recorded duration are omitted."""
    parts = [f"{name};dur={duration:.1f}" for name, duration in durations_ms if duration is not None]
    return ", ".join(parts)


def execution_response_headers(execution: ExecutionMetadata) -> dict[str, str]:
    """Response headers derived from `ExecutionMetadata` (task 2.4 / 3.2)."""
    headers = {
        HEADER_BACKEND_INVOCATION_ID: execution.backend_invocation_id,
        HEADER_CORRELATION_ID: execution.correlation_id,
        HEADER_KNOWLEDGE_GENERATION: execution.knowledge_generation,
        HEADER_SECURITY_SCOPE: execution.security_scope,
        HEADER_PROMPT_VERSION: execution.prompt_version,
        HEADER_MODEL_VERSION: execution.logical_model_version,
        HEADER_EMBEDDING_CALLED: str(execution.embedding_called).lower(),
        HEADER_SEARCH_CALLED: str(execution.search_called).lower(),
        HEADER_MODEL_CALLED: str(execution.model_called).lower(),
    }
    if execution.input_tokens is not None:
        headers[HEADER_INPUT_TOKENS] = str(execution.input_tokens)
    if execution.output_tokens is not None:
        headers[HEADER_OUTPUT_TOKENS] = str(execution.output_tokens)

    server_timing = build_server_timing(
        ("embedding", execution.embedding_duration_ms),
        ("search", execution.search_duration_ms),
        ("model", execution.model_duration_ms),
    )
    if server_timing:
        headers[HEADER_SERVER_TIMING] = server_timing
    return headers


class Timer:
    """Small monotonic timer used to record dependency durations without
    coupling `rag.service` to `time` directly (keeps it easy to test)."""

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        self.duration_ms: Optional[float] = None
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.duration_ms = (time.monotonic() - self._start) * 1000
