"""
Typed Pydantic contracts for the RAG query domain (task 2.2).

All wire models use camelCase aliases (matching `docs/APIM-CACHING-EXTENSIBILITY.md`)
while remaining accessible from Python via their snake_case field names.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Base class for wire contracts: camelCase JSON, snake_case Python."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )


# ── Request ────────────────────────────────────────────────────────────────


class QueryRequest(ApiModel):
    """Inbound question payload.

    `knowledge_generation` and `security_scope` may be present for display
    purposes only — see `openspec/changes/add-apim-exact-cache-demo/design.md`
    ("Publish generation through trusted APIM configuration"). The backend
    MUST NOT let a caller choose its own cache partition; the authoritative
    values come from trusted context headers (`rag.headers`) or config
    defaults, never from this body. See `rag.service.resolve_trusted_context`.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    question: str
    knowledge_generation: Optional[str] = None
    security_scope: Optional[str] = None


# ── Retrieval ─────────────────────────────────────────────────────────────


class RetrievedChunk(ApiModel):
    """Pure mapping of one Azure AI Search hit (task 2.1 / 2.5)."""

    id: str
    type: str
    page: int
    source_file: str
    document_id: Optional[str] = None
    image_blob: Optional[str] = None
    text_for_embedding: str = ""
    score: Optional[float] = None


# ── Response ──────────────────────────────────────────────────────────────


class QueryCitation(ApiModel):
    source_file: str
    page: int
    type: str
    chunk_id: Optional[str] = None
    image_blob: Optional[str] = None


class DependencyName(str, Enum):
    EMBEDDING = "embedding"
    SEARCH = "search"
    MODEL = "model"


class ExecutionMetadata(ApiModel):
    """Non-sensitive backend execution proof (task 2.4).

    Never carries raw question text, retrieved content, or prompts — only
    identifiers, called/not-called flags, durations, and token counts.
    """

    backend_invocation_id: str
    correlation_id: str
    knowledge_generation: str
    security_scope: str
    prompt_version: str
    logical_model_version: str
    cache_mode: str = "none"

    embedding_called: bool = False
    embedding_duration_ms: Optional[float] = None
    search_called: bool = False
    search_duration_ms: Optional[float] = None
    model_called: bool = False
    model_duration_ms: Optional[float] = None

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    result_count: int = 0


class QueryResponse(ApiModel):
    answer: str
    citations: list[QueryCitation] = Field(default_factory=list)
    execution: ExecutionMetadata


class QueryErrorResponse(ApiModel):
    error: str
    message: str
    correlation_id: str


# ── Errors ────────────────────────────────────────────────────────────────


class QuestionValidationError(ValueError):
    """Raised by `rag.validation` for a missing, empty, malformed, or
    over-limit question. `reason` is a short machine-readable code suitable
    for telemetry (never the raw question)."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        super().__init__(detail)


class DependencyError(Exception):
    """Raised when embedding, retrieval, or answer generation fails.
    Carries enough structure to report a non-success response and
    correlated telemetry without leaking raw content (task 2.2 / spec
    "Dependency failure")."""

    def __init__(self, dependency: DependencyName, message: str, cause: Optional[BaseException] = None) -> None:
        self.dependency = dependency
        self.message = message
        self.cause = cause
        super().__init__(f"{dependency.value} dependency failed: {message}")
