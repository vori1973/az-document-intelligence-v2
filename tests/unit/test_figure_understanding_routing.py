"""
Unit tests for step4c_understanding.py — routing outcome mapping.

The routing table is the recall-preserving contract: only a confident
"not meaningful" verdict rejects a figure. Every other combination retains.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pytest
from activities.step4c_understanding import CATEGORIES, FIGURE_SCHEMA, _routing_outcome


def _understanding(is_meaningful: bool, confidence: str) -> dict:
    return {
        "is_meaningful": is_meaningful,
        "category": "diagram",
        "model_confidence_label": confidence,
        "contains_text": False,
        "short_description": "A schematic of the device.",
        "visible_labels": [],
        "device_or_component_terms": [],
        "procedure_actions": [],
        "warnings_or_constraints": [],
        "search_keywords": [],
        "uncertainty": [],
        "needs_larger_context_crop": False,
    }


# ── _routing_outcome — full verdict matrix ────────────────────────────────


class TestRoutingOutcomeMatrix:
    @pytest.mark.parametrize("confidence", ["high", "medium", "low"])
    def test_meaningful_always_retains(self, confidence):
        assert _routing_outcome(_understanding(True, confidence)) == "retain"

    def test_confident_negative_rejects(self):
        assert _routing_outcome(_understanding(False, "high")) == "reject"

    @pytest.mark.parametrize("confidence", ["medium", "low"])
    def test_unconfident_negative_retains_low_confidence(self, confidence):
        assert _routing_outcome(_understanding(False, confidence)) == "retain_low_confidence"

    def test_missing_understanding_retains_unverified(self):
        assert _routing_outcome(None) == "retain_unverified"


# ── _routing_outcome — malformed or partial payloads ──────────────────────


class TestRoutingOutcomeDegradedInput:
    def test_empty_dict_is_treated_as_unconfident_negative(self):
        # No is_meaningful and no confidence label — must not reject.
        assert _routing_outcome({}) == "retain_low_confidence"

    def test_missing_confidence_label_does_not_reject(self):
        assert _routing_outcome({"is_meaningful": False}) == "retain_low_confidence"

    def test_missing_is_meaningful_with_high_confidence_rejects(self):
        # A high-confidence verdict that omits the flag is a confident negative.
        assert _routing_outcome(
            {"model_confidence_label": "high"}
        ) == "reject"

    def test_unknown_confidence_label_does_not_reject(self):
        assert _routing_outcome(
            {"is_meaningful": False, "model_confidence_label": "very-high"}
        ) == "retain_low_confidence"


# ── Retention accounting ──────────────────────────────────────────────────


class TestRetentionAccounting:
    def test_only_reject_is_excluded_from_retained(self):
        outcomes = ["retain", "retain_low_confidence", "retain_unverified", "reject"]
        retained = [o for o in outcomes if o != "reject"]
        assert len(retained) == 3

    def test_every_outcome_is_a_known_value(self):
        produced = {
            _routing_outcome(None),
            _routing_outcome(_understanding(True, "high")),
            _routing_outcome(_understanding(False, "high")),
            _routing_outcome(_understanding(False, "low")),
        }
        assert produced == {
            "retain_unverified", "retain", "reject", "retain_low_confidence",
        }


# ── Structured output schema ──────────────────────────────────────────────


class TestFigureSchema:
    def test_schema_is_strict(self):
        assert FIGURE_SCHEMA["additionalProperties"] is False

    def test_every_property_is_required(self):
        assert set(FIGURE_SCHEMA["required"]) == set(FIGURE_SCHEMA["properties"])

    def test_category_uses_the_controlled_taxonomy(self):
        assert FIGURE_SCHEMA["properties"]["category"]["enum"] == CATEGORIES

    def test_confidence_label_is_constrained(self):
        assert FIGURE_SCHEMA["properties"]["model_confidence_label"]["enum"] == [
            "high", "medium", "low",
        ]

    def test_taxonomy_includes_an_unknown_escape_hatch(self):
        assert "unknown" in CATEGORIES
