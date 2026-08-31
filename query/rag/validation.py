"""
Bounded question validation (task 2.3).

Keeps validation independent of HTTP framework and Pydantic parsing errors so
the caller (the Function route, or a test) gets a single, stable exception
type with a short machine-readable reason code.
"""

from __future__ import annotations

from .contracts import QuestionValidationError

MIN_QUESTION_LENGTH = 1
MAX_QUESTION_LENGTH = 2000


def validate_question(raw: object, *, max_length: int = MAX_QUESTION_LENGTH) -> str:
    """Validate and return the trimmed question text.

    Raises `QuestionValidationError` for a missing, non-string, empty, or
    over-limit question. Trimming only removes surrounding whitespace here —
    normalization (case/whitespace-collapse) for cache identity happens
    separately in `rag.normalize`.
    """
    if raw is None:
        raise QuestionValidationError("missing", "question is required")
    if not isinstance(raw, str):
        raise QuestionValidationError("invalid_type", "question must be a string")

    trimmed = raw.strip()
    if len(trimmed) < MIN_QUESTION_LENGTH:
        raise QuestionValidationError("empty", "question must not be empty")
    if len(raw) > max_length:
        raise QuestionValidationError(
            "too_long", f"question exceeds the {max_length}-character limit"
        )
    return trimmed


def validate_top_k(raw: object, *, default: int, minimum: int = 1, maximum: int = 20) -> int:
    """Validate an optional caller-supplied result count, bounded to a safe range."""
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise QuestionValidationError("invalid_top_k", "topK must be an integer")
    if raw < minimum or raw > maximum:
        raise QuestionValidationError(
            "top_k_out_of_range", f"topK must be between {minimum} and {maximum}"
        )
    return raw
