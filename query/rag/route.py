"""
Internal HTTP query route (task 3.2).

The only module in `rag` that depends on `azure.functions`. Trusts APIM
context headers (`rag.headers`), propagates correlation, sets execution
headers and `Server-Timing`, and returns explicit non-success responses for
invalid requests and dependency failures — never a partial result presented
as a successful (and therefore cacheable) answer.

Direct, unauthenticated access to this route is rejected by App Service
Authentication/Authorization, which only admits tokens issued for the
backend's Entra application and presented by an allow-listed application —
the APIM gateway identity plus any approved test principals (see
`infra/modules/query_functions.bicep`).
"""

from __future__ import annotations

import logging

import azure.functions as func
from pydantic import ValidationError

from .auth import get_credential
from .config import QueryConfig
from .contracts import DependencyError, QuestionValidationError, QueryErrorResponse, QueryRequest
from .headers import HEADER_CORRELATION_ID, execution_response_headers, resolve_trusted_context
from .service import run_query

logger = logging.getLogger("rag.route")

_DEPENDENCY_STATUS = 502


def handle_query_request(req: func.HttpRequest, *, config: QueryConfig | None = None) -> func.HttpResponse:
    """Entry point called by the Function App's HTTP trigger."""
    config = config or QueryConfig.from_env()
    headers = dict(req.headers)
    trusted = resolve_trusted_context(headers, config)

    try:
        body = req.get_json()
    except ValueError:
        return _error_response(
            status=400,
            error="invalid_json",
            message="request body must be valid JSON",
            correlation_id=trusted.correlation_id,
        )

    try:
        request = QueryRequest.model_validate(body)
    except ValidationError as exc:
        return _error_response(
            status=400,
            error="invalid_request",
            message=str(exc),
            correlation_id=trusted.correlation_id,
        )

    try:
        response = run_query(
            request,
            headers,
            config=config,
            credential=get_credential(),
            trusted_context=trusted,
        )
    except QuestionValidationError as exc:
        return _error_response(
            status=400,
            error=exc.reason,
            message=str(exc),
            correlation_id=trusted.correlation_id,
        )
    except DependencyError as exc:
        logger.warning("query dependency failure: %s", exc.dependency.value)
        return _error_response(
            status=_DEPENDENCY_STATUS,
            error=f"{exc.dependency.value}_unavailable",
            message=exc.message,
            correlation_id=trusted.correlation_id,
        )

    response_headers = execution_response_headers(response.execution)
    return func.HttpResponse(
        body=response.model_dump_json(by_alias=True),
        status_code=200,
        mimetype="application/json",
        headers=response_headers,
    )


def _error_response(*, status: int, error: str, message: str, correlation_id: str) -> func.HttpResponse:
    payload = QueryErrorResponse(error=error, message=message, correlation_id=correlation_id)
    return func.HttpResponse(
        body=payload.model_dump_json(by_alias=True),
        status_code=status,
        mimetype="application/json",
        headers={HEADER_CORRELATION_ID: correlation_id},
    )
