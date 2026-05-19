"""
Unit tests for step5_chunks.py — RAG chunk building logic.

Tests are pure Python — no Azure SDK calls, no blob storage.
All tested functions are pure data-transformation logic.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pytest
from activities.step5_chunks import (
    _token_count,
    _union_polygon,
    _parse_mistral_tables,
    _build_adi_cell_grid,
    _normalize_adi_grid,
    _normalize_mistral_table,
    _last_sentences,
)


# ── _token_count ──────────────────────────────────────────────────────────


class TestTokenCount:
    def test_empty_string(self):
        assert _token_count("") == 0

    def test_whitespace_only(self):
        assert _token_count("   ") == 0

    def test_single_word(self):
        assert _token_count("hello") == 1

    def test_multiple_words(self):
        assert _token_count("hello world foo") == 3

    def test_extra_whitespace(self):
        assert _token_count("  hello   world  ") == 2


# ── _union_polygon ────────────────────────────────────────────────────────


class TestUnionPolygon:
    def test_single_polygon(self):
        poly = [[0, 0, 2, 0, 2, 1, 0, 1]]
        result = _union_polygon(poly)
        assert result == [0, 0, 2, 0, 2, 1, 0, 1]

    def test_two_adjacent_polygons(self):
        # First: x 0-2, y 0-1 | Second: x 2-4, y 0-1
        result = _union_polygon([
            [0, 0, 2, 0, 2, 1, 0, 1],
            [2, 0, 4, 0, 4, 1, 2, 1],
        ])
        # Union: x 0-4, y 0-1
        assert result[0] == 0   # min_x
        assert result[2] == 4   # max_x (TL→TR)
        assert result[1] == 0   # min_y
        assert result[7] == 1   # max_y (BL)

    def test_overlapping_polygons(self):
        result = _union_polygon([
            [0, 0, 3, 0, 3, 3, 0, 3],
            [1, 1, 4, 1, 4, 4, 1, 4],
        ])
        # min_x=0, max_x=4, min_y=0, max_y=4
        assert result[0] == 0
        assert result[2] == 4

    def test_empty_list_returns_empty(self):
        assert _union_polygon([]) == []

    def test_returns_four_corners(self):
        result = _union_polygon([[0, 0, 5, 0, 5, 3, 0, 3]])
        # [min_x, min_y, max_x, min_y, max_x, max_y, min_x, max_y]
        assert len(result) == 8


# ── _parse_mistral_tables ─────────────────────────────────────────────────


class TestParseMistralTables:
    def test_empty_markdown(self):
        assert _parse_mistral_tables("") == []

    def test_no_tables(self):
        md = "Just some prose text.\n\nAnother paragraph."
        assert _parse_mistral_tables(md) == []

    def test_simple_table(self):
        md = (
            "| Name | Age |\n"
            "| --- | --- |\n"
            "| Alice | 30 |\n"
            "| Bob | 25 |\n"
        )
        tables = _parse_mistral_tables(md)
        assert len(tables) == 1
        assert tables[0]["headers"] == [["Name", "Age"]]
        assert tables[0]["data"] == [["Alice", "30"], ["Bob", "25"]]

    def test_table_with_multi_row_header(self):
        md = (
            "| Category | Sub |\n"
            "| Detail | Value |\n"
            "| --- | --- |\n"
            "| A | 1 |\n"
        )
        tables = _parse_mistral_tables(md)
        assert len(tables) == 1
        assert len(tables[0]["headers"]) == 2
        assert tables[0]["data"] == [["A", "1"]]

    def test_two_separate_tables(self):
        md = (
            "| A | B |\n"
            "| --- | --- |\n"
            "| 1 | 2 |\n"
            "\nSome prose between.\n\n"
            "| X | Y |\n"
            "| --- | --- |\n"
            "| 3 | 4 |\n"
        )
        tables = _parse_mistral_tables(md)
        assert len(tables) == 2

    def test_continuation_line_joined(self):
        # Mistral sometimes wraps long cell content — should be joined
        md = (
            "| Col1 | Col2\n"
            "continuation of col2 |\n"
            "| --- | --- |\n"
            "| A | B |\n"
        )
        tables = _parse_mistral_tables(md)
        assert len(tables) == 1
        # Header row should have cells joined
        header_row = tables[0]["headers"][0]
        assert len(header_row) == 2

    def test_separator_with_alignment(self):
        md = (
            "| Name | Value |\n"
            "| :--- | ---: |\n"
            "| foo | 42 |\n"
        )
        tables = _parse_mistral_tables(md)
        assert len(tables) == 1
        assert tables[0]["data"] == [["foo", "42"]]


# ── _build_adi_cell_grid ──────────────────────────────────────────────────


class TestBuildAdiCellGrid:
    def _make_cell(self, row, col, content, row_span=1, col_span=1):
        return {
            "row_index": row,
            "column_index": col,
            "content": content,
            "row_span": row_span,
            "column_span": col_span,
            "kind": "body",
        }

    def test_simple_2x2_grid(self):
        cells = [
            self._make_cell(0, 0, "A"),
            self._make_cell(0, 1, "B"),
            self._make_cell(1, 0, "C"),
            self._make_cell(1, 1, "D"),
        ]
        values, row_spanned = _build_adi_cell_grid(cells, 2, 2)
        assert values == [["A", "B"], ["C", "D"]]
        assert row_spanned == [[False, False], [False, False]]

    def test_rowspan_propagates_value(self):
        # Cell at (0,0) spans 2 rows
        cells = [
            self._make_cell(0, 0, "Merged", row_span=2),
            self._make_cell(0, 1, "Top"),
            self._make_cell(1, 1, "Bottom"),
        ]
        values, row_spanned = _build_adi_cell_grid(cells, 2, 2)
        assert values[0][0] == "Merged"
        assert values[1][0] == "Merged"  # propagated
        assert row_spanned[0][0] is False  # origin row not marked
        assert row_spanned[1][0] is True   # continuation row marked

    def test_colspan_propagates_value(self):
        cells = [
            self._make_cell(0, 0, "Wide", col_span=2),
            self._make_cell(1, 0, "Left"),
            self._make_cell(1, 1, "Right"),
        ]
        values, _ = _build_adi_cell_grid(cells, 2, 2)
        assert values[0][0] == "Wide"
        assert values[0][1] == "Wide"

    def test_checkbox_selected_translated(self):
        cells = [self._make_cell(0, 0, ":selected:")]
        values, _ = _build_adi_cell_grid(cells, 1, 1)
        assert values[0][0] == "checked"

    def test_checkbox_unselected_translated(self):
        cells = [self._make_cell(0, 0, ":unselected:")]
        values, _ = _build_adi_cell_grid(cells, 1, 1)
        assert values[0][0] == "unchecked"

    def test_mixed_checkbox_stripped(self):
        cells = [self._make_cell(0, 0, "Option A :selected: extra")]
        values, _ = _build_adi_cell_grid(cells, 1, 1)
        assert ":selected:" not in values[0][0]
        assert "Option A" in values[0][0]

    def test_empty_grid(self):
        values, row_spanned = _build_adi_cell_grid([], 0, 0)
        assert values == []
        assert row_spanned == []


# ── _normalize_adi_grid ───────────────────────────────────────────────────


class TestNormalizeAdiGrid:
    def test_no_change_when_no_groups(self):
        values = [["A", "1"], ["B", "2"]]
        result = _normalize_adi_grid(values, 2, 2)
        assert result == [["A", "1"], ["B", "2"]]

    def test_propagates_single_value_in_group(self):
        # Col 0 has "Group" spanning 3 rows; col 1 has value only in row 1
        values = [
            ["Group", ""],
            ["Group", "42"],
            ["Group", ""],
        ]
        result = _normalize_adi_grid(values, 3, 2)
        # "42" should be propagated to all rows in the group
        assert result[0][1] == "42"
        assert result[1][1] == "42"
        assert result[2][1] == "42"

    def test_does_not_propagate_when_multiple_values(self):
        values = [
            ["Group", "10"],
            ["Group", "20"],
            ["Group", ""],
        ]
        result = _normalize_adi_grid(values, 3, 2)
        # Multiple non-empty values → don't propagate
        assert result[0][1] == "10"
        assert result[1][1] == "20"
        assert result[2][1] == ""

    def test_single_column_unchanged(self):
        values = [["A"], ["A"], ["B"]]
        result = _normalize_adi_grid(values, 3, 1)
        assert result == [["A"], ["A"], ["B"]]

    def test_empty_group_label_ignored(self):
        values = [["", "1"], ["", "2"]]
        result = _normalize_adi_grid(values, 2, 2)
        # Empty label → not treated as a group → no propagation
        assert result == [["", "1"], ["", "2"]]


# ── _normalize_mistral_table ──────────────────────────────────────────────


class TestNormalizeMistralTable:
    def test_empty_rows(self):
        result = _normalize_mistral_table([], [], [], [])
        assert result == []

    def test_fill_down_simple(self):
        # Row 0 has "Group", Row 1 is empty → fill-down from row 0
        rows = [["Group", "Val"], ["", "Other"]]
        adi_values = [["Group", "Val"], ["", "Other"]]
        adi_row_spanned = [[False, False], [False, False]]
        row_indices = [0, 1]
        result = _normalize_mistral_table(rows, adi_values, adi_row_spanned, row_indices)
        assert result[1][0] == "Group"  # filled down

    def test_no_fill_when_value_present(self):
        rows = [["A", "1"], ["B", "2"]]
        adi_values = [["A", "1"], ["B", "2"]]
        adi_row_spanned = [[False, False], [False, False]]
        result = _normalize_mistral_table(rows, adi_values, adi_row_spanned, [0, 1])
        assert result[0][0] == "A"
        assert result[1][0] == "B"

    def test_adi_rowspan_override(self):
        # ADI detected row 1 col 0 is row-spanned → use ADI value
        rows = [["Mistral-A", "Val"], ["split", "Other"]]
        adi_values = [["ADI-Full", "Val"], ["ADI-Full", "Other"]]
        adi_row_spanned = [[False, False], [True, False]]
        result = _normalize_mistral_table(rows, adi_values, adi_row_spanned, [0, 1])
        assert result[1][0] == "ADI-Full"

    def test_fill_right_column_span(self):
        # Mistral: col 1 empty, col 0 = "300 Cases", ADI col 1 = "Cases"
        # "Cases" is in "300 Cases" and differs → col 1 gets col 0's value
        rows = [["300 Cases", ""]]
        adi_values = [["300", "Cases"]]
        adi_row_spanned = [[False, False]]
        result = _normalize_mistral_table(rows, adi_values, adi_row_spanned, [0])
        assert result[0][1] == "300 Cases"

    def test_fill_right_no_propagate_when_same(self):
        # ADI col 1 == col 0 → column-span duplication, don't propagate
        rows = [["Value", ""]]
        adi_values = [["Value", "Value"]]
        adi_row_spanned = [[False, False]]
        result = _normalize_mistral_table(rows, adi_values, adi_row_spanned, [0])
        assert result[0][1] == ""  # not propagated


# ── _last_sentences ───────────────────────────────────────────────────────


class TestLastSentences:
    def test_empty_string(self):
        assert _last_sentences("", 2) == ""

    def test_too_short_returns_empty(self):
        # Under MIN_LEAD_IN_CHARS (30) → skip
        assert _last_sentences("Hi.", 2) == ""

    def test_single_long_sentence(self):
        text = "This is a sufficiently long sentence that meets the minimum character threshold."
        result = _last_sentences(text, 2)
        assert result == text

    def test_returns_last_n_sentences(self):
        text = "First sentence. Second sentence. Third sentence."
        result = _last_sentences(text, 2)
        assert "Third sentence" in result
        assert "Second sentence" in result
        assert "First sentence" not in result

    def test_single_sentence_requested(self):
        text = "Sentence one. Sentence two. Sentence three here."
        result = _last_sentences(text, 1)
        assert "Sentence three" in result
        assert "Sentence one" not in result

    def test_fewer_sentences_than_n(self):
        text = "Only one long enough sentence here to pass the threshold check."
        result = _last_sentences(text, 3)
        assert result == text.strip()
