"""
Unit tests for document-derived context in step4c_understanding.py
(add-document-derived-prompt).

Covers: context appears only in the user message, never in SYSTEM_PROMPT;
truncation of over-long nearby text; and description-quality signal
computation.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from activities.step4c_understanding import (
    FIGURE_CONTEXT_MAX_CHARS,
    SYSTEM_PROMPT,
    _build_user_content,
    _truncate_at_word_boundary,
)
from models.types import FigureCandidate, FigureFeatures


def _candidate(**overrides) -> FigureCandidate:
    defaults = dict(
        document_id="doc1",
        page=3,
        figure_index=0,
        figure_id="fig-0",
        caption=None,
        features=FigureFeatures(
            width_ratio=0.3, height_ratio=0.3, area_ratio=0.09, aspect_ratio=1.0,
        ),
    )
    defaults.update(overrides)
    return FigureCandidate(**defaults)


# ── SYSTEM_PROMPT is document-independent ─────────────────────────────────


class TestSystemPromptIsFixed:
    def test_system_prompt_does_not_change_across_documents(self):
        # SYSTEM_PROMPT is a module-level constant — this asserts it stays
        # byte-identical regardless of which candidate is being processed.
        prompt_for_doc_a = SYSTEM_PROMPT
        _build_user_content(
            _candidate(document_title="Robotic Knee System Guide"), "aaaa"
        )
        prompt_for_doc_b = SYSTEM_PROMPT
        _build_user_content(
            _candidate(document_title="Hardware Catalog v3"), "bbbb"
        )
        assert prompt_for_doc_a == prompt_for_doc_b == SYSTEM_PROMPT

    def test_system_prompt_states_recognition_not_assertion_rule(self):
        assert "not evidence that something is present" in SYSTEM_PROMPT.lower() \
            or "never evidence that something is" in SYSTEM_PROMPT.lower()

    def test_system_prompt_contains_no_interpolation_artifacts(self):
        # A fixed constant should never contain str.format / f-string leftovers.
        assert "{" not in SYSTEM_PROMPT and "}" not in SYSTEM_PROMPT


# ── Context appears only in the user message ──────────────────────────────


class TestContextInUserMessageOnly:
    def test_document_context_appears_in_user_text_block(self):
        candidate = _candidate(
            document_title="Robotic Knee System Guide",
            section_heading="Femoral Preparation",
            nearby_text="Insert the femoral tracker array as shown.",
        )
        content = _build_user_content(candidate, "base64img")
        text_block = content[0]["text"]
        assert "Robotic Knee System Guide" in text_block
        assert "Femoral Preparation" in text_block
        assert "Insert the femoral tracker array" in text_block
        assert "Document context" in text_block

    def test_missing_context_omits_the_context_block(self):
        candidate = _candidate()
        content = _build_user_content(candidate, "base64img")
        text_block = content[0]["text"]
        assert "Document context" not in text_block

    def test_partial_context_includes_only_what_is_available(self):
        candidate = _candidate(document_title="Hardware Catalog v3")
        content = _build_user_content(candidate, "base64img")
        text_block = content[0]["text"]
        assert "Hardware Catalog v3" in text_block
        assert "Section heading" not in text_block
        assert "Nearby page text" not in text_block

    def test_user_content_still_carries_the_image(self):
        content = _build_user_content(_candidate(), "base64img")
        assert content[1]["type"] == "image_url"
        assert "base64img" in content[1]["image_url"]["url"]


# ── Truncation ──────────────────────────────────────────────────────────


class TestTruncateAtWordBoundary:
    def test_short_text_is_unchanged(self):
        assert _truncate_at_word_boundary("short text", 600) == "short text"

    def test_long_text_is_truncated_at_word_boundary(self):
        text = "word " * 200  # 1000 chars, well over the limit
        truncated = _truncate_at_word_boundary(text, 50)
        assert len(truncated) <= 51  # allow for the ellipsis character
        assert not truncated.rstrip("…").endswith("wor")  # no mid-word cut
        assert truncated.endswith("…")

    def test_truncation_uses_configured_max_chars_in_prompt_assembly(self):
        nearby = "x" * (FIGURE_CONTEXT_MAX_CHARS + 400)
        candidate = _candidate(nearby_text=nearby)
        content = _build_user_content(candidate, "base64img")
        text_block = content[0]["text"]
        nearby_line = next(
            line for line in text_block.splitlines() if line.startswith("Nearby page text:")
        )
        supplied = nearby_line[len("Nearby page text: "):]
        assert len(supplied) <= FIGURE_CONTEXT_MAX_CHARS + 1  # +1 for ellipsis
        assert len(supplied) < len(nearby)


# ── Description-quality signals ────────────────────────────────────────────

from activities.step4c_understanding import _is_generic_opener, _quality_signals


def _record(is_meaningful=True, short_description="A femoral tracker array.",
            visible_labels=None, understanding_present=True):
    if not understanding_present:
        return {"understanding": None}
    return {
        "understanding": {
            "is_meaningful": is_meaningful,
            "short_description": short_description,
            "visible_labels": visible_labels if visible_labels is not None else ["ART-204"],
        }
    }


class TestIsGenericOpener:
    def test_illustration_opener_is_generic(self):
        assert _is_generic_opener("An illustration showing a tracker array.") is True

    def test_diagram_opener_is_generic(self):
        assert _is_generic_opener("A diagram of the surgical workflow.") is True

    def test_specific_opener_is_not_generic(self):
        assert _is_generic_opener("A femoral tracker array mounted on a pin.") is False

    def test_case_insensitive(self):
        assert _is_generic_opener("AN ILLUSTRATION of a device.") is True

    def test_none_or_empty_is_not_generic(self):
        assert _is_generic_opener(None) is False
        assert _is_generic_opener("") is False


class TestQualitySignals:
    def test_rates_computed_over_meaningful_described_figures(self):
        records = [
            _record(short_description="An illustration of a tracker.", visible_labels=[]),
            _record(short_description="A femoral tracker array.", visible_labels=["ART-204"]),
            _record(short_description="A diagram of the workflow.", visible_labels=[]),
            _record(short_description="A tibial cutting guide.", visible_labels=["TCG-1"]),
        ]
        signals = _quality_signals(records)
        assert signals["meaningful_described_count"] == 4
        assert signals["generic_opener_count"] == 2
        assert signals["generic_opener_rate"] == 0.5
        assert signals["unlabelled_count"] == 2
        assert signals["unlabelled_rate"] == 0.5

    def test_non_meaningful_and_undescribed_records_are_excluded(self):
        records = [
            _record(is_meaningful=False, short_description="page furniture"),
            _record(understanding_present=False),
            _record(short_description="", visible_labels=[]),
            _record(short_description="A tibial cutting guide.", visible_labels=["TCG-1"]),
        ]
        signals = _quality_signals(records)
        assert signals["meaningful_described_count"] == 1
        assert signals["generic_opener_rate"] == 0.0
        assert signals["unlabelled_rate"] == 0.0

    def test_zero_described_figures_does_not_divide_by_zero(self):
        signals = _quality_signals([])
        assert signals["meaningful_described_count"] == 0
        assert signals["generic_opener_count"] == 0
        assert signals["generic_opener_rate"] == 0.0
        assert signals["unlabelled_count"] == 0
        assert signals["unlabelled_rate"] == 0.0

    def test_all_generic_and_all_unlabelled(self):
        records = [
            _record(short_description="An illustration.", visible_labels=[]),
            _record(short_description="A photo of a part.", visible_labels=[]),
        ]
        signals = _quality_signals(records)
        assert signals["generic_opener_rate"] == 1.0
        assert signals["unlabelled_rate"] == 1.0
