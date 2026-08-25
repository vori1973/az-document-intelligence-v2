import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from activities.step4c_understanding import (
    _derive_budget,
    _select_model,
    _select_qualified_figures,
)
from models.types import FigureCandidate, FigureFeatures, Step4CResult


def _candidate(page: int, figure_index: int, area_ratio: float) -> FigureCandidate:
    return FigureCandidate(
        document_id="doc-1",
        page=page,
        figure_index=figure_index,
        figure_id=f"p{page}_fig{figure_index}",
        tight_crop_uri=f"figures/p{page}-fig{figure_index}.png",
        features=FigureFeatures(
            width_ratio=0.5,
            height_ratio=0.5,
            area_ratio=area_ratio,
            aspect_ratio=1.0,
        ),
    )


class TestBudgetDerivation:
    def test_budget_scales_with_page_count(self):
        assert _derive_budget(2, allowance=4, ceiling=500) == 8
        assert _derive_budget(10, allowance=4, ceiling=500) == 40

    def test_budget_clamps_at_ceiling(self):
        assert _derive_budget(200, allowance=4, ceiling=500) == 500

    def test_single_page_document(self):
        assert _derive_budget(1, allowance=4, ceiling=500) == 4

    @pytest.mark.parametrize(
        ("page_count", "allowance", "ceiling"),
        [(0, 4, 500), (1, 0, 500), (1, 4, 0)],
    )
    def test_invalid_configuration_is_rejected(self, page_count, allowance, ceiling):
        with pytest.raises(ValueError):
            _derive_budget(page_count, allowance, ceiling)


class TestPageBalancedSelection:
    def test_binding_budget_represents_every_page_before_second_figures(self):
        figures = [
            _candidate(page, figure_index, 0.4 - figure_index * 0.1)
            for page in range(1, 5)
            for figure_index in range(3)
        ]

        selected = _select_qualified_figures(figures, budget=6)

        assert {candidate.page for candidate in selected} == {1, 2, 3, 4}
        assert [candidate.page for candidate in selected] == sorted(
            candidate.page for candidate in selected
        )
        selected_by_page = {
            page: [candidate.figure_index for candidate in selected if candidate.page == page]
            for page in range(1, 5)
        }
        assert selected_by_page == {1: [0, 1], 2: [0, 1], 3: [0], 4: [0]}

    def test_largest_figure_on_each_page_is_selected_first(self):
        figures = [
            _candidate(1, 0, 0.1),
            _candidate(1, 1, 0.5),
            _candidate(2, 0, 0.2),
            _candidate(2, 1, 0.4),
        ]

        selected = _select_qualified_figures(figures, budget=2)

        assert [(candidate.page, candidate.figure_index) for candidate in selected] == [
            (1, 1),
            (2, 1),
        ]

    def test_non_binding_budget_preserves_all_figures_and_order(self):
        figures = [
            _candidate(1, 0, 0.1),
            _candidate(1, 1, 0.5),
            _candidate(2, 0, 0.2),
        ]

        assert _select_qualified_figures(figures, budget=4) is figures


class TestModelSelection:
    @pytest.mark.parametrize("count", [0, 59, 60])
    def test_at_or_below_threshold_uses_premium(self, count):
        assert _select_model(count, "premium", "economy", 60) == "premium"

    def test_above_threshold_uses_economy(self):
        assert _select_model(61, "premium", "economy", 60) == "economy"

    @pytest.mark.parametrize("count", [1, 60, 61, 500])
    def test_identical_tiers_have_no_observable_tiering(self, count):
        assert _select_model(count, "same-model", "same-model", 60) == "same-model"


class TestStepResultTelemetry:
    @pytest.mark.parametrize(
        ("qualified", "budget", "analyzed", "bound"),
        [(10, 40, 10, False), (12, 8, 8, True)],
    )
    def test_budget_fields_are_serialized(self, qualified, budget, analyzed, bound):
        result = Step4CResult(
            understood=analyzed,
            retained=analyzed,
            rejected=0,
            model="gpt-4o-mini",
            duration_ms=100,
            qualified_count=qualified,
            budget=budget,
            analyzed_count=analyzed,
            budget_bound=bound,
        )

        assert result.model_dump() == {
            "understood": analyzed,
            "retained": analyzed,
            "rejected": 0,
            "outcomes": {},
            "model": "gpt-4o-mini",
            "duration_ms": 100,
            "qualified_count": qualified,
            "budget": budget,
            "analyzed_count": analyzed,
            "budget_bound": bound,
            "meaningful_described_count": 0,
            "generic_opener_count": 0,
            "generic_opener_rate": 0.0,
            "unlabelled_count": 0,
            "unlabelled_rate": 0.0,
        }
