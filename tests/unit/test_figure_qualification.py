"""
Unit tests for step4a_figures.py — deterministic figure qualification (4B).

Covers the hard rejection rules, the reference-overrides-geometry case, and
the routing signals attached to surviving-but-uncertain candidates.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from activities.step4a_figures import (
    FURNITURE_AREA_CEILING,
    HEADER_FOOTER_OVERLAP_THRESHOLD,
    MAX_AREA_RATIO,
    MAX_ASPECT_RATIO,
    MIN_AREA_RATIO,
    REPEAT_PAGE_THRESHOLD,
    _has_reference,
    _overlap_ratio,
    _polygon_bbox,
    _qualify,
)
from models.types import FigureFeatures


def _features(
    area_ratio: float = 0.25,
    aspect_ratio: float = 1.5,
    header_overlap_ratio: float = 0.0,
    footer_overlap_ratio: float = 0.0,
    repeat_page_count: int = 1,
) -> FigureFeatures:
    return FigureFeatures(
        width_ratio=0.5,
        height_ratio=0.5,
        area_ratio=area_ratio,
        aspect_ratio=aspect_ratio,
        header_overlap_ratio=header_overlap_ratio,
        footer_overlap_ratio=footer_overlap_ratio,
        repeat_page_count=repeat_page_count,
    )


# ── _polygon_bbox ─────────────────────────────────────────────────────────


class TestPolygonBbox:
    def test_empty_polygon(self):
        assert _polygon_bbox([]) is None

    def test_too_few_coordinates(self):
        assert _polygon_bbox([1.0, 2.0]) is None

    def test_rectangle(self):
        assert _polygon_bbox([1.0, 2.0, 5.0, 2.0, 5.0, 6.0, 1.0, 6.0]) == (1.0, 2.0, 5.0, 6.0)

    def test_unordered_points(self):
        assert _polygon_bbox([5.0, 6.0, 1.0, 2.0, 5.0, 2.0, 1.0, 6.0]) == (1.0, 2.0, 5.0, 6.0)


# ── _overlap_ratio ────────────────────────────────────────────────────────


class TestOverlapRatio:
    def test_no_overlap(self):
        assert _overlap_ratio((0, 0, 1, 1), (5, 5, 6, 6)) == 0.0

    def test_full_containment(self):
        assert _overlap_ratio((1, 1, 2, 2), (0, 0, 10, 10)) == 1.0

    def test_partial_overlap(self):
        # box is 2x2; the other covers exactly its left half.
        assert _overlap_ratio((0, 0, 2, 2), (0, 0, 1, 2)) == 0.5


# ── _has_reference ────────────────────────────────────────────────────────


class TestHasReference:
    def test_caption_is_decisive(self):
        assert _has_reference("Figure 3. Handpiece", [], None) is True

    def test_blank_caption_is_not_a_reference(self):
        assert _has_reference("   ", [], None) is False

    def test_no_caption_and_no_bbox(self):
        assert _has_reference(None, [], None) is False

    def test_nearby_referencing_text_counts(self):
        page_text = [((1.0, 1.0, 3.0, 1.2), "see figure 3 for details")]
        assert _has_reference(None, page_text, (1.0, 1.5, 3.0, 3.0)) is True

    def test_distant_referencing_text_is_ignored(self):
        page_text = [((1.0, 20.0, 3.0, 20.2), "see figure 3 for details")]
        assert _has_reference(None, page_text, (1.0, 1.0, 3.0, 3.0)) is False

    def test_nearby_text_without_reference_terms(self):
        page_text = [((1.0, 1.0, 3.0, 1.2), "the device operates continuously")]
        assert _has_reference(None, page_text, (1.0, 1.5, 3.0, 3.0)) is False


# ── _qualify — hard rejections ────────────────────────────────────────────


class TestQualifyRejections:
    def test_structural_noise_from_header_overlap(self):
        status, reason, signals = _qualify(
            _features(header_overlap_ratio=HEADER_FOOTER_OVERLAP_THRESHOLD + 0.1),
            caption=None,
            has_reference=False,
        )
        assert status == "rejected"
        assert reason == "structural_noise"
        assert signals == []

    def test_structural_noise_from_footer_overlap(self):
        status, reason, _ = _qualify(
            _features(footer_overlap_ratio=HEADER_FOOTER_OVERLAP_THRESHOLD + 0.1),
            caption=None,
            has_reference=False,
        )
        assert status == "rejected"
        assert reason == "structural_noise"

    def test_low_value_graphic_when_too_small(self):
        status, reason, _ = _qualify(
            _features(area_ratio=MIN_AREA_RATIO / 2),
            caption=None,
            has_reference=False,
        )
        assert status == "rejected"
        assert reason == "low_value_graphic"

    def test_decorative_geometry_when_too_elongated(self):
        status, reason, _ = _qualify(
            _features(
                area_ratio=FURNITURE_AREA_CEILING / 2,
                aspect_ratio=MAX_ASPECT_RATIO + 1.0,
            ),
            caption=None,
            has_reference=False,
        )
        assert status == "rejected"
        assert reason == "decorative_geometry"

    def test_thresholds_are_inclusive_for_furniture_overlap(self):
        status, reason, _ = _qualify(
            _features(header_overlap_ratio=HEADER_FOOTER_OVERLAP_THRESHOLD),
            caption=None,
            has_reference=False,
        )
        assert status == "rejected"
        assert reason == "structural_noise"

    def test_repeated_small_figure_is_furniture(self):
        status, reason, _ = _qualify(
            _features(
                area_ratio=FURNITURE_AREA_CEILING / 2,
                repeat_page_count=REPEAT_PAGE_THRESHOLD + 1,
            ),
            caption=None,
            has_reference=False,
        )
        assert status == "rejected"
        assert reason == "repeated_furniture"

    def test_repeat_threshold_is_retained(self):
        status, reason, _ = _qualify(
            _features(
                area_ratio=FURNITURE_AREA_CEILING / 2,
                repeat_page_count=REPEAT_PAGE_THRESHOLD,
            ),
            caption=None,
            has_reference=False,
        )
        assert status == "candidate"
        assert reason is None

    def test_small_non_repeating_figure_is_retained(self):
        status, reason, _ = _qualify(
            _features(
                area_ratio=MIN_AREA_RATIO,
                repeat_page_count=1,
            ),
            caption=None,
            has_reference=False,
        )
        assert status == "candidate"
        assert reason is None

    def test_elongated_figure_within_new_limit_is_retained(self):
        status, reason, _ = _qualify(
            _features(
                area_ratio=FURNITURE_AREA_CEILING / 2,
                aspect_ratio=MAX_ASPECT_RATIO,
            ),
            caption=None,
            has_reference=False,
        )
        assert status == "candidate"
        assert reason is None

    def test_elongated_figure_with_substantial_area_is_retained(self):
        status, reason, _ = _qualify(
            _features(
                area_ratio=FURNITURE_AREA_CEILING,
                aspect_ratio=MAX_ASPECT_RATIO + 1.0,
            ),
            caption=None,
            has_reference=False,
        )
        assert status == "candidate"
        assert reason is None


# ── _qualify — reference overrides geometry ───────────────────────────────


class TestReferenceOverridesGeometry:
    def test_reference_saves_furniture_overlap(self):
        status, reason, signals = _qualify(
            _features(header_overlap_ratio=HEADER_FOOTER_OVERLAP_THRESHOLD + 0.2),
            caption=None,
            has_reference=True,
        )
        assert status == "candidate"
        assert reason is None
        assert "furniture_overlap_with_reference" in signals

    def test_reference_saves_tiny_figure(self):
        status, reason, signals = _qualify(
            _features(area_ratio=MIN_AREA_RATIO / 10),
            caption=None,
            has_reference=True,
        )
        assert status == "candidate"
        assert reason is None
        assert "small_figure_with_reference" in signals

    def test_reference_saves_elongated_figure(self):
        status, reason, _ = _qualify(
            _features(aspect_ratio=MAX_ASPECT_RATIO + 5.0),
            caption=None,
            has_reference=True,
        )
        assert status == "candidate"
        assert reason is None

    def test_caption_saves_elongated_figure(self):
        status, reason, signals = _qualify(
            _features(aspect_ratio=MAX_ASPECT_RATIO + 5.0),
            caption="Figure 1. Wide banner diagram",
            has_reference=False,
        )
        assert status == "candidate"
        assert reason is None
        assert "caption_missing" not in signals

    def test_reference_saves_repeated_furniture(self):
        status, reason, _ = _qualify(
            _features(
                area_ratio=FURNITURE_AREA_CEILING / 2,
                repeat_page_count=REPEAT_PAGE_THRESHOLD + 1,
            ),
            caption=None,
            has_reference=True,
        )
        assert status == "candidate"
        assert reason is None

    def test_caption_saves_repeated_furniture(self):
        status, reason, _ = _qualify(
            _features(
                area_ratio=FURNITURE_AREA_CEILING / 2,
                repeat_page_count=REPEAT_PAGE_THRESHOLD + 1,
            ),
            caption="Figure 1. Product logo",
            has_reference=True,
        )
        assert status == "candidate"
        assert reason is None

    def test_caption_alone_does_not_save_tiny_figure(self):
        # Only has_reference vetoes the area rule; a caption normally implies
        # a reference, but the rule itself must stay caption-independent.
        status, reason, _ = _qualify(
            _features(area_ratio=MIN_AREA_RATIO / 10),
            caption="Figure 2. Safety icon",
            has_reference=False,
        )
        assert status == "rejected"
        assert reason == "low_value_graphic"


# ── _qualify — routing signals ────────────────────────────────────────────


class TestQualifyRoutingSignals:
    def test_clean_figure_has_no_signals(self):
        status, reason, signals = _qualify(
            _features(), caption="Figure 4. Device overview", has_reference=True
        )
        assert status == "candidate"
        assert reason is None
        assert signals == []

    def test_missing_caption_signal(self):
        _, _, signals = _qualify(_features(), caption=None, has_reference=True)
        assert signals == ["caption_missing"]

    def test_full_page_graphic_signal(self):
        _, _, signals = _qualify(
            _features(area_ratio=MAX_AREA_RATIO + 0.05),
            caption="Figure 5. Full page schematic",
            has_reference=True,
        )
        assert "full_page_graphic" in signals

    def test_multiple_signals_accumulate(self):
        _, _, signals = _qualify(
            _features(
                area_ratio=MIN_AREA_RATIO / 2,
                header_overlap_ratio=HEADER_FOOTER_OVERLAP_THRESHOLD + 0.1,
            ),
            caption=None,
            has_reference=True,
        )
        assert set(signals) == {
            "caption_missing",
            "small_figure_with_reference",
            "furniture_overlap_with_reference",
        }
