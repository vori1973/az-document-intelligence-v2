"""
Orchestrates validation → embedding → hybrid retrieval → grounded answer →
response construction + telemetry for one query (tasks 2.1-2.4).

Framework-agnostic: `rag.route` (used by the Function App's HTTP trigger)
calls `run_query` and is the only module that knows about `azure.functions`.
"""

from __future__ import annotations

from .answer import generate_answer, hits_to_citations
from .clients import build_aoai_client, build_search_headers
from .config import QueryConfig
from .contracts import (
    DependencyError,
    DependencyName,
    ExecutionMetadata,
    QueryRequest,
    QueryResponse,
)
from .headers import Timer, TrustedContext, new_backend_invocation_id, resolve_trusted_context
from .retrieval import embed_text, hybrid_search
from .telemetry import log_query_error, log_query_start, log_query_success
from .validation import validate_question


def run_query(
    request: QueryRequest,
    request_headers: dict,
    *,
    config: QueryConfig,
    credential,
    trusted_context: TrustedContext | None = None,
) -> QueryResponse:
    """Run one grounded RAG query.

    Raises `QuestionValidationError` for an invalid request (handled by the
    route as a 400) and `DependencyError` for an embedding/Search/model
    failure (handled by the route as a 502), matching the spec scenarios
    "Invalid query request" and "Dependency failure".
    """
    trusted = trusted_context or resolve_trusted_context(request_headers, config)

    # Validation happens before any backend invocation is recorded — an
    # invalid request never reaches Search or the model, and is never
    # reported (or cacheable) as a backend execution.
    question = validate_question(request.question, max_length=config.max_question_length)
    backend_invocation_id = new_backend_invocation_id()
    log_query_start(
        correlation_id=trusted.correlation_id,
        backend_invocation_id=backend_invocation_id,
        cache_mode=trusted.cache_mode,
        knowledge_generation=trusted.knowledge_generation,
        security_scope=trusted.security_scope,
        prompt_version=trusted.prompt_version,
        logical_model_version=trusted.logical_model_version,
    )

    execution_partial = {
        "backend_invocation_id": backend_invocation_id,
        "correlation_id": trusted.correlation_id,
        "knowledge_generation": trusted.knowledge_generation,
        "security_scope": trusted.security_scope,
        "prompt_version": trusted.prompt_version,
        "logical_model_version": trusted.logical_model_version,
        "cache_mode": trusted.cache_mode,
    }

    try:
        aoai_client = build_aoai_client(credential, config)
        search_headers = build_search_headers(credential)

        with Timer() as embed_timer:
            try:
                embedding = embed_text(aoai_client, config.embed_model, question)
            except Exception as exc:  # noqa: BLE001 - normalize any embedding failure
                raise DependencyError(DependencyName.EMBEDDING, str(exc), cause=exc) from exc

        with Timer() as search_timer:
            try:
                raw_hits = hybrid_search(
                    config.search_endpoint,
                    config.search_index,
                    search_headers,
                    embedding,
                    search_text=question,
                    k=config.default_top_k,
                    only_figures=False,
                    api_version=config.search_api_version,
                )
            except Exception as exc:  # noqa: BLE001 - normalize any Search failure
                raise DependencyError(DependencyName.SEARCH, str(exc), cause=exc) from exc

        with Timer() as model_timer:
            try:
                answer_result = generate_answer(
                    aoai_client, config.chat_model, question, raw_hits
                )
            except Exception as exc:  # noqa: BLE001 - normalize any model failure
                raise DependencyError(DependencyName.MODEL, str(exc), cause=exc) from exc
    except DependencyError as exc:
        log_query_error(
            **execution_partial,
            dependency=exc.dependency.value,
            error_type=type(exc.cause or exc).__name__,
        )
        raise

    citations = hits_to_citations(raw_hits)
    execution = ExecutionMetadata(
        **execution_partial,
        embedding_called=True,
        embedding_duration_ms=embed_timer.duration_ms,
        search_called=True,
        search_duration_ms=search_timer.duration_ms,
        model_called=True,
        model_duration_ms=model_timer.duration_ms,
        input_tokens=answer_result.input_tokens,
        output_tokens=answer_result.output_tokens,
        result_count=len(raw_hits),
    )

    log_query_success(
        backend_invocation_id=backend_invocation_id,
        correlation_id=trusted.correlation_id,
        embedding_duration_ms=embed_timer.duration_ms,
        search_duration_ms=search_timer.duration_ms,
        model_duration_ms=model_timer.duration_ms,
        input_tokens=answer_result.input_tokens,
        output_tokens=answer_result.output_tokens,
        result_count=len(raw_hits),
    )

    return QueryResponse(answer=answer_result.text, citations=citations, execution=execution)
