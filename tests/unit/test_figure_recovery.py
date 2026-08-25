"""
Unit tests for the missed-figure recovery cross-check
(add-missed-figure-detection): points-to-inches conversion, placement-to-
polygon derivation, overlap matching, per-page gating, figure-index
collision-freedom, provenance assignment, and the disabled-recovery
fallback path.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import activities.step4a_figures as step4a
from activities.step1_preanalysis import _is_cross_check_eligible
from activities.step4a_figures import (
    POINTS_PER_INCH,
    _already_detected,
    _bbox_to_polygon,
    _first_recovered_index,
    _load_recovery_inputs,
    _placement_rect_to_inches,
)
from models.types import FigureCandidate, FigureLocation, ImagePlacement, PageImageClassification


# ── _placement_rect_to_inches ───────────────────────────────────────────────


class TestPlacementRectToInches:
    def test_converts_points_to_inches(self):
        # 72 points == 1 inch, 144 points == 2 inches
        bbox = _placement_rect_to_inches([0.0, 0.0, 144.0, 72.0])
        assert bbox == (0.0, 0.0, 2.0, 1.0)

    def test_non_zero_origin(self):
        bbox = _placement_rect_to_inches([72.0, 36.0, 216.0, 108.0])
        assert bbox == (1.0, 0.5, 3.0, 1.5)

    def test_empty_rect_returns_none(self):
        assert _placement_rect_to_inches([]) is None

    def test_wrong_length_returns_none(self):
        assert _placement_rect_to_inches([1.0, 2.0, 3.0]) is None

    def test_round_trips_with_points_per_inch_constant(self):
        rect = [0.0, 0.0, POINTS_PER_INCH * 3, POINTS_PER_INCH * 4]
        assert _placement_rect_to_inches(rect) == (0.0, 0.0, 3.0, 4.0)


# ── _bbox_to_polygon ─────────────────────────────────────────────────────


class TestBboxToPolygon:
    def test_derives_four_corner_polygon(self):
        polygon = _bbox_to_polygon((1.0, 2.0, 3.0, 4.0))
        assert polygon == [1.0, 2.0, 3.0, 2.0, 3.0, 4.0, 1.0, 4.0]

    def test_polygon_bbox_recovers_original_bbox(self):
        bbox = (0.5, 0.5, 2.5, 3.5)
        polygon = _bbox_to_polygon(bbox)
        assert step4a._polygon_bbox(polygon) == bbox


# ── _already_detected — overlap matching ──────────────────────────────────


class TestAlreadyDetected:
    def test_exact_match_is_detected(self):
        bbox = (1.0, 1.0, 3.0, 3.0)
        assert _already_detected(bbox, [(1.0, 1.0, 3.0, 3.0)], threshold=0.5) is True

    def test_substantial_overlap_is_detected(self):
        placement = (1.0, 1.0, 3.0, 3.0)
        adi_figure = (1.1, 1.1, 3.1, 3.1)  # nearly identical, slightly offset
        assert _already_detected(placement, [adi_figure], threshold=0.5) is True

    def test_partial_overlap_below_threshold_is_not_detected(self):
        placement = (0.0, 0.0, 2.0, 2.0)
        adi_figure = (1.8, 1.8, 3.8, 3.8)  # tiny sliver of overlap
        assert _already_detected(placement, [adi_figure], threshold=0.5) is False

    def test_no_overlap_is_not_detected(self):
        placement = (0.0, 0.0, 1.0, 1.0)
        adi_figure = (5.0, 5.0, 6.0, 6.0)
        assert _already_detected(placement, [adi_figure], threshold=0.3) is False

    def test_checked_in_both_directions(self):
        # Placement fully contained inside a much larger ADI region: overlap
        # of (placement covered by adi) is 100%, but (adi covered by
        # placement) is small — the max of the two must still trigger.
        placement = (1.0, 1.0, 1.5, 1.5)
        adi_figure = (0.0, 0.0, 10.0, 10.0)
        assert _already_detected(placement, [adi_figure], threshold=0.9) is True

    def test_no_existing_bboxes_is_never_detected(self):
        assert _already_detected((0.0, 0.0, 1.0, 1.0), [], threshold=0.1) is False


# ── Per-page gating ────────────────────────────────────────────────────────


class TestCrossCheckEligibility:
    def test_scanned_page_is_ineligible(self):
        assert _is_cross_check_eligible(coverage_ratio=0.95, enumerable=True) is False

    def test_partial_coverage_page_is_eligible(self):
        assert _is_cross_check_eligible(coverage_ratio=0.44, enumerable=True) is True

    def test_not_enumerable_page_is_ineligible(self):
        assert _is_cross_check_eligible(coverage_ratio=0.1, enumerable=False) is False

    def test_boundary_at_threshold_is_ineligible(self):
        from activities.step1_preanalysis import FIGURE_SCANNED_PAGE_COVERAGE_THRESHOLD
        assert _is_cross_check_eligible(
            coverage_ratio=FIGURE_SCANNED_PAGE_COVERAGE_THRESHOLD, enumerable=True
        ) is False

    def test_mixed_document_is_gated_per_page(self):
        # A scanned page and a digitally-born page in the same document each
        # get their own independent eligibility decision.
        scanned = PageImageClassification(
            page_number=1, has_text=False, image_coverage_ratio=0.97,
            cross_check_eligible=_is_cross_check_eligible(0.97, True),
        )
        digital = PageImageClassification(
            page_number=2, has_text=True, image_coverage_ratio=0.2,
            cross_check_eligible=_is_cross_check_eligible(0.2, True),
        )
        assert scanned.cross_check_eligible is False
        assert digital.cross_check_eligible is True


# ── Figure index collision-freedom ─────────────────────────────────────────


class TestFirstRecoveredIndex:
    def test_starts_above_highest_adi_index(self):
        assert _first_recovered_index(max_adi_figure_index=8) == 9

    def test_starts_at_zero_when_no_adi_figures(self):
        assert _first_recovered_index(max_adi_figure_index=-1) == 0

    def test_sequential_recovered_indices_never_collide_with_adi(self):
        adi_indices = {0, 1, 2, 5, 9}
        next_index = _first_recovered_index(max(adi_indices))
        recovered = {next_index, next_index + 1, next_index + 2}
        assert adi_indices.isdisjoint(recovered)


# ── Provenance defaults ─────────────────────────────────────────────────────


class TestProvenanceDefaults:
    def test_figure_candidate_defaults_to_reader_provenance(self):
        candidate = FigureCandidate(
            document_id="doc-1", page=1, figure_index=0, figure_id="fig-0",
            bounding_polygon=[0, 0, 1, 0, 1, 1, 0, 1],
        )
        assert candidate.provenance == "reader"

    def test_figure_location_defaults_to_reader_provenance(self):
        location = FigureLocation(
            figure_index=0, figure_id="fig-0", page_number=1,
            polygon=[0, 0, 1, 0, 1, 1, 0, 1],
        )
        assert location.provenance == "reader"

    def test_recovered_provenance_is_explicit(self):
        candidate = FigureCandidate(
            document_id="doc-1", page=6, figure_index=10, figure_id="recovered-p6-10",
            bounding_polygon=[0, 0, 1, 0, 1, 1, 0, 1], provenance="recovered",
        )
        assert candidate.provenance == "recovered"

    def test_old_artifacts_without_provenance_deserialize_as_reader(self):
        # Simulates an older figures.json record written before this field
        # existed — deserialization must not fail and must default sanely.
        raw = {
            "document_id": "doc-1", "page": 1, "figure_index": 0,
            "figure_id": "fig-0", "bounding_polygon": [0, 0, 1, 0, 1, 1, 0, 1],
        }
        candidate = FigureCandidate.model_validate(raw)
        assert candidate.provenance == "reader"


# ── _load_recovery_inputs — disabled / unavailable fallback ────────────────


class TestLoadRecoveryInputs:
    def test_returns_none_when_artifacts_are_missing(self, monkeypatch):
        def _raise(*args, **kwargs):
            raise FileNotFoundError("no such artifact")

        monkeypatch.setattr(step4a, "download_json_artifact", _raise)
        pages, placements = _load_recovery_inputs("doc-1", "run-1")
        assert pages is None
        assert placements is None

    def test_parses_available_artifacts(self, monkeypatch):
        step1_result = {
            "pages": [
                {
                    "page_number": 1, "has_text": True,
                    "image_coverage_ratio": 0.1, "cross_check_eligible": True,
                    "enumerable": True,
                },
            ],
        }
        placements_raw = [
            {"page_number": 1, "rect": [0.0, 0.0, 72.0, 72.0], "width_px": 100, "height_px": 100},
        ]

        def _fake_download(doc_id, run_id, filename):
            if filename == "step1-result.json":
                return step1_result
            if filename == "image-placements.json":
                return placements_raw
            raise AssertionError(f"unexpected artifact {filename}")

        monkeypatch.setattr(step4a, "download_json_artifact", _fake_download)
        pages, placements = _load_recovery_inputs("doc-1", "run-1")

        assert pages[1].cross_check_eligible is True
        assert isinstance(pages[1], PageImageClassification)
        assert len(placements[1]) == 1
        assert isinstance(placements[1][0], ImagePlacement)

    def test_recovery_disabled_by_default(self):
        # FIGURE_RECOVERY_ENABLED defaults to false unless explicitly set.
        assert step4a.FIGURE_RECOVERY_ENABLED is False


# ── _recovered_candidate_has_reference ──────────────────────────────────────


class TestRecoveredCandidateHasReference:
    """Recovered candidates must not receive the has_reference escape hatch
    via proximity text (fix-recovered-figure-noise): they never carry a real
    ADI caption, so on dense pages a generic reference term coincidentally
    near a tiny icon/emoji fragment would otherwise defeat MIN_AREA_RATIO
    for exactly the sub-pixel placements it exists to reject.
    """

    def test_always_false(self):
        assert step4a._recovered_candidate_has_reference() is False

    def test_tiny_recovered_figure_is_rejected_even_with_nearby_reference_term(self):
        # A dense-page scenario: a "note" paragraph sits right next to a
        # sub-pixel-scale recovered placement. If recovered candidates used
        # _has_reference's proximity fallback (as reader-detected figures
        # do), this would incorrectly survive MIN_AREA_RATIO.
        features = step4a.FigureFeatures(
            width_ratio=0.01,
            height_ratio=0.01,
            area_ratio=0.0001,  # far below MIN_AREA_RATIO (0.002 default)
            aspect_ratio=1.0,
            header_overlap_ratio=0.0,
            footer_overlap_ratio=0.0,
            normalized_position_group="0.50:0.50:0.01:0.01",
        )
        page_text = [((0.4, 1.4, 3.0, 1.6), "See the note below for details.")]
        # Reader-detected figures at this bbox *would* be saved by proximity text...
        assert step4a._has_reference(None, page_text, (0.5, 1.5, 0.6, 1.6)) is True
        # ...but recovered candidates never get that escape hatch:
        has_ref = step4a._recovered_candidate_has_reference()
        status, reason, _ = step4a._qualify(features, caption=None, has_reference=has_ref)
        assert status == "rejected"
        assert reason == "low_value_graphic"
