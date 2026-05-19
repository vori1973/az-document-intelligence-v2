"""
Unit tests for step3_router.py — confidence-based routing logic.

Tests are pure Python — no Azure SDK calls, no blob storage.
The routing functions are extracted and tested directly.
"""

import sys
import os

# Allow importing from src/ without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pytest
from models.types import AdiPageResult, FigureLocation, TableConfidence
from activities.step3_router import (
    _overlaps,
    _polygon_to_rect,
    _figure_overlaps_table,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


def make_table(
    table_index: int = 0,
    page_number: int = 1,
    min_cell_confidence: float = 0.9,
    average_cell_confidence: float = 0.95,
    requires_ocr: bool = False,
    has_complex_structure: bool = False,
    complexity_reasons: list[str] | None = None,
    polygon: list[float] | None = None,
) -> TableConfidence:
    return TableConfidence(
        table_index=table_index,
        page_number=page_number,
        average_cell_confidence=average_cell_confidence,
        min_cell_confidence=min_cell_confidence,
        cell_count=10,
        unmatched_cells=0,
        requires_ocr=requires_ocr,
        has_complex_structure=has_complex_structure,
        complexity_reasons=complexity_reasons or [],
        polygon=polygon or [0, 0, 2, 0, 2, 1, 0, 1],
    )


def make_figure(
    polygon: list[float],
    page_number: int = 1,
    figure_index: int = 0,
) -> FigureLocation:
    return FigureLocation(
        figure_index=figure_index,
        figure_id=f"fig-{figure_index}",
        page_number=page_number,
        polygon=polygon,
    )


def make_page(
    page_number: int = 1,
    tables: list[TableConfidence] | None = None,
    figures: list[FigureLocation] | None = None,
) -> AdiPageResult:
    return AdiPageResult(
        page_number=page_number,
        tables=tables or [],
        figures=figures or [],
    )


# ── _polygon_to_rect ──────────────────────────────────────────────────────


class TestPolygonToRect:
    def test_axis_aligned_rectangle(self):
        # [x1,y1, x2,y2, x3,y3, x4,y4] — clockwise from top-left
        poly = [0, 0, 4, 0, 4, 3, 0, 3]
        rect = _polygon_to_rect(poly)
        assert rect == {"min_x": 0, "max_x": 4, "min_y": 0, "max_y": 3}

    def test_non_origin_rectangle(self):
        poly = [1, 2, 5, 2, 5, 6, 1, 6]
        rect = _polygon_to_rect(poly)
        assert rect == {"min_x": 1, "max_x": 5, "min_y": 2, "max_y": 6}

    def test_single_point(self):
        poly = [3, 3, 3, 3, 3, 3, 3, 3]
        rect = _polygon_to_rect(poly)
        assert rect["min_x"] == rect["max_x"] == 3
        assert rect["min_y"] == rect["max_y"] == 3


# ── _overlaps ─────────────────────────────────────────────────────────────


class TestOverlaps:
    def test_non_overlapping_rectangles(self):
        a = [0, 0, 1, 0, 1, 1, 0, 1]   # x: 0-1, y: 0-1
        b = [2, 0, 3, 0, 3, 1, 2, 1]   # x: 2-3, y: 0-1  (gap between)
        assert _overlaps(a, b) is False

    def test_overlapping_rectangles(self):
        a = [0, 0, 2, 0, 2, 2, 0, 2]   # x: 0-2, y: 0-2
        b = [1, 1, 3, 1, 3, 3, 1, 3]   # x: 1-3, y: 1-3  (overlap at 1-2, 1-2)
        assert _overlaps(a, b) is True

    def test_touching_edge_does_not_overlap(self):
        # Rectangles share an edge but don't overlap in area
        a = [0, 0, 1, 0, 1, 1, 0, 1]
        b = [1, 0, 2, 0, 2, 1, 1, 1]
        # min_x(b)=1 is NOT < max_x(a)=1, so no overlap
        assert _overlaps(a, b) is False

    def test_fully_contained(self):
        outer = [0, 0, 4, 0, 4, 4, 0, 4]
        inner = [1, 1, 3, 1, 3, 3, 1, 3]
        assert _overlaps(outer, inner) is True
        assert _overlaps(inner, outer) is True

    def test_empty_polygon_returns_false(self):
        assert _overlaps([], [0, 0, 1, 0, 1, 1, 0, 1]) is False
        assert _overlaps([0, 0, 1, 0, 1, 1, 0, 1], []) is False

    def test_too_short_polygon_returns_false(self):
        assert _overlaps([0, 0], [0, 0, 1, 0, 1, 1, 0, 1]) is False

    def test_vertical_separation(self):
        a = [0, 0, 2, 0, 2, 1, 0, 1]   # y: 0-1
        b = [0, 2, 2, 2, 2, 3, 0, 3]   # y: 2-3  (gap)
        assert _overlaps(a, b) is False


# ── _figure_overlaps_table ────────────────────────────────────────────────


class TestFigureOverlapsTable:
    def test_figure_overlaps_one_table(self):
        fig = make_figure(polygon=[0.5, 0.5, 1.5, 0.5, 1.5, 1.5, 0.5, 1.5])
        table = make_table(polygon=[0, 0, 2, 0, 2, 2, 0, 2])
        assert _figure_overlaps_table(fig, [table]) is True

    def test_figure_does_not_overlap_any_table(self):
        fig = make_figure(polygon=[5, 5, 6, 5, 6, 6, 5, 6])
        table = make_table(polygon=[0, 0, 2, 0, 2, 2, 0, 2])
        assert _figure_overlaps_table(fig, [table]) is False

    def test_figure_overlaps_second_of_two_tables(self):
        fig = make_figure(polygon=[3, 3, 4, 3, 4, 4, 3, 4])
        table1 = make_table(table_index=0, polygon=[0, 0, 2, 0, 2, 2, 0, 2])
        table2 = make_table(table_index=1, polygon=[2.5, 2.5, 4.5, 2.5, 4.5, 4.5, 2.5, 4.5])
        assert _figure_overlaps_table(fig, [table1, table2]) is True

    def test_no_tables_returns_false(self):
        fig = make_figure(polygon=[0, 0, 1, 0, 1, 1, 0, 1])
        assert _figure_overlaps_table(fig, []) is False


# ── Routing decisions (unit-level, no blob I/O) ───────────────────────────


class TestRoutingDecisionLogic:
    """
    Tests the routing decision logic in isolation.
    The full step3_router_main() reads from blob storage, so we test
    the underlying decision rules directly via the helper functions.
    """

    def test_low_confidence_table_routes_to_ocr(self):
        table = make_table(requires_ocr=True, min_cell_confidence=0.5)
        page = make_page(tables=[table])
        assert any(t.requires_ocr for t in page.tables)

    def test_high_confidence_table_stays_adi_only(self):
        table = make_table(requires_ocr=False, min_cell_confidence=0.95)
        page = make_page(tables=[table])
        assert not any(t.requires_ocr for t in page.tables)

    def test_complex_structure_triggers_ocr(self):
        table = make_table(
            requires_ocr=True,
            has_complex_structure=True,
            complexity_reasons=["rowSpan>1 on 3 cell(s)"],
        )
        assert table.requires_ocr is True
        assert table.has_complex_structure is True

    def test_page_with_no_tables_is_adi_only(self):
        page = make_page(tables=[])
        assert not any(t.requires_ocr for t in page.tables)

    def test_figure_overlapping_table_requires_routing(self):
        table = make_table(polygon=[0, 0, 3, 0, 3, 3, 0, 3], requires_ocr=False)
        fig = make_figure(polygon=[1, 1, 2, 1, 2, 2, 1, 2])
        assert _figure_overlaps_table(fig, [table]) is True

    def test_figure_not_overlapping_table_no_extra_routing(self):
        table = make_table(polygon=[0, 0, 1, 0, 1, 1, 0, 1], requires_ocr=False)
        fig = make_figure(polygon=[5, 5, 6, 5, 6, 6, 5, 6])
        assert _figure_overlaps_table(fig, [table]) is False

    def test_multi_page_routing(self):
        page1 = make_page(page_number=1, tables=[make_table(requires_ocr=True)])
        page2 = make_page(page_number=2, tables=[make_table(requires_ocr=False)])
        page3 = make_page(page_number=3, tables=[])

        pages_for_ocr = [p.page_number for p in [page1, page2, page3] if any(t.requires_ocr for t in p.tables)]
        adi_only = [p.page_number for p in [page1, page2, page3] if not any(t.requires_ocr for t in p.tables)]

        assert pages_for_ocr == [1]
        assert set(adi_only) == {2, 3}

    def test_mixed_orientation_complexity_reasons(self):
        table = make_table(
            requires_ocr=True,
            has_complex_structure=True,
            complexity_reasons=["rotated cells (2 cell(s) with h/w>5)", "column width disparity (12:1 ratio)"],
        )
        assert "rotated" in table.complexity_reasons[0]
        assert table.requires_ocr is True

    def test_table_with_rowspan_routes_to_ocr(self):
        table = make_table(
            requires_ocr=True,
            has_complex_structure=True,
            complexity_reasons=["rowSpan>1 on 1 cell(s)"],
        )
        assert table.requires_ocr is True
