"""Unit tests for bounded question validation (task 2.5)."""

from __future__ import annotations

import pytest

from rag.contracts import QuestionValidationError
from rag.validation import (
    MAX_QUESTION_LENGTH,
    validate_question,
    validate_top_k,
)


def test_validate_question_trims_surrounding_whitespace():
    assert validate_question("  What is the tire pressure?  ") == "What is the tire pressure?"


def test_validate_question_rejects_none():
    with pytest.raises(QuestionValidationError) as exc_info:
        validate_question(None)
    assert exc_info.value.reason == "missing"


def test_validate_question_rejects_non_string():
    with pytest.raises(QuestionValidationError) as exc_info:
        validate_question(12345)
    assert exc_info.value.reason == "invalid_type"


def test_validate_question_rejects_empty_string():
    with pytest.raises(QuestionValidationError) as exc_info:
        validate_question("")
    assert exc_info.value.reason == "empty"


def test_validate_question_rejects_whitespace_only_string():
    with pytest.raises(QuestionValidationError) as exc_info:
        validate_question("   \n\t  ")
    assert exc_info.value.reason == "empty"


def test_validate_question_rejects_over_limit_question():
    with pytest.raises(QuestionValidationError) as exc_info:
        validate_question("a" * (MAX_QUESTION_LENGTH + 1))
    assert exc_info.value.reason == "too_long"


def test_validate_question_accepts_question_at_exact_limit():
    question = "a" * MAX_QUESTION_LENGTH
    assert validate_question(question) == question


def test_validate_question_honors_custom_max_length():
    with pytest.raises(QuestionValidationError) as exc_info:
        validate_question("hello world", max_length=5)
    assert exc_info.value.reason == "too_long"


def test_validate_top_k_returns_default_when_absent():
    assert validate_top_k(None, default=8) == 8


def test_validate_top_k_accepts_value_in_range():
    assert validate_top_k(5, default=8, minimum=1, maximum=20) == 5


def test_validate_top_k_rejects_out_of_range_value():
    with pytest.raises(QuestionValidationError) as exc_info:
        validate_top_k(999, default=8, minimum=1, maximum=20)
    assert exc_info.value.reason == "top_k_out_of_range"


def test_validate_top_k_rejects_non_integer():
    with pytest.raises(QuestionValidationError) as exc_info:
        validate_top_k("8", default=8)
    assert exc_info.value.reason == "invalid_top_k"


def test_validate_top_k_rejects_bool():
    """`bool` is a subclass of `int` in Python — must not silently pass as a
    valid topK."""
    with pytest.raises(QuestionValidationError) as exc_info:
        validate_top_k(True, default=8)
    assert exc_info.value.reason == "invalid_top_k"
