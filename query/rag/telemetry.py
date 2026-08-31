"""
Structured, privacy-preserving telemetry for the query domain (task 2.4).

Mirrors `src/shared/telemetry.py`'s pattern (structured `custom_dimensions`
logged through the Functions host's Application Insights integration) but
enforces the query domain's stricter redaction contract: raw questions,
retrieved chunk text, complete prompts, cached response bodies, secrets,
access tokens, and direct user identifiers are never accepted as telemetry
fields — see `docs/APIM-CACHING-EXTENSIBILITY.md` ("Telemetry contract").
"""

from __future__ import annotations

import logging
import os
from typing import Any

if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(logger_name="rag")

logger = logging.getLogger("rag.query")
logger.setLevel(logging.INFO)

# Field names that must never appear in emitted telemetry, even if a caller
# passes them by mistake. Checked defensively in `_emit` so a coding error
# elsewhere cannot silently leak content into Application Insights.
DISALLOWED_FIELDS = frozenset(
    {
        "question",
        "raw_question",
        "prompt",
        "messages",
        "answer",
        "answer_text",
        "chunk_text",
        "text_for_embedding",
        "response_body",
        "authorization",
        "access_token",
        "token",
        "api_key",
        "user_id",
        "patient_id",
    }
)


def _emit(event: str, props: dict[str, Any]) -> None:
    leaked = DISALLOWED_FIELDS.intersection(props)
    if leaked:
        raise ValueError(f"refusing to emit disallowed telemetry field(s): {sorted(leaked)}")
    logger.info(event, extra=props)


def log_query_start(
    *,
    correlation_id: str,
    backend_invocation_id: str,
    cache_mode: str,
    knowledge_generation: str,
    security_scope: str,
    prompt_version: str,
    logical_model_version: str,
) -> None:
    _emit(
        "rag.query.start",
        {
            "correlation_id": correlation_id,
            "backend_invocation_id": backend_invocation_id,
            "cache_mode": cache_mode,
            "knowledge_generation": knowledge_generation,
            "security_scope": security_scope,
            "prompt_version": prompt_version,
            "logical_model_version": logical_model_version,
        },
    )


def log_query_success(*, correlation_id: str, backend_invocation_id: str, **dimensions: Any) -> None:
    _emit(
        "rag.query.success",
        {
            "correlation_id": correlation_id,
            "backend_invocation_id": backend_invocation_id,
            **dimensions,
        },
    )


def log_query_error(
    *,
    correlation_id: str,
    backend_invocation_id: str,
    dependency: str,
    error_type: str,
    **dimensions: Any,
) -> None:
    _emit(
        "rag.query.error",
        {
            "correlation_id": correlation_id,
            "backend_invocation_id": backend_invocation_id,
            "dependency": dependency,
            "error_type": error_type,
            **dimensions,
        },
    )
