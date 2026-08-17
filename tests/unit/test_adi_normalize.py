"""
Regression tests for ADI raw-result key normalization.

These exist because of a production bug: `as_dict()` returns the REST wire
format (camelCase), downstream code read snake_case, and every lookup was
paired with a default like `or 1`. The result was an entire search index
whose citations claimed page 1, with no error anywhere.

The fixture below is a trimmed copy of a real `adi-raw.json` from a
multi-page document, so a future SDK change that reverts the casing fails
here instead of silently corrupting citations again.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from shared.adi_normalize import _to_snake, normalize_adi_dict


# ── _to_snake ─────────────────────────────────────────────────────────────


def test_to_snake_converts_camel_case():
    assert _to_snake("pageNumber") == "page_number"
    assert _to_snake("boundingRegions") == "bounding_regions"
    assert _to_snake("columnSpan") == "column_span"


def test_to_snake_leaves_already_snake_untouched():
    assert _to_snake("page_number") == "page_number"
    assert _to_snake("content") == "content"


def test_to_snake_handles_leading_capital():
    assert _to_snake("PageNumber") == "page_number"


# ── normalize_adi_dict ────────────────────────────────────────────────────


def test_normalizes_nested_structures():
    raw = {
        "pages": [{"pageNumber": 3, "width": 8.5, "unit": "inch"}],
        "paragraphs": [
            {"boundingRegions": [{"pageNumber": 3, "polygon": [0.1, 0.2]}]}
        ],
    }
    out = normalize_adi_dict(raw)

    assert out["pages"][0]["page_number"] == 3
    assert out["paragraphs"][0]["bounding_regions"][0]["page_number"] == 3


def test_values_are_not_modified():
    """Only keys are rewritten — content must survive byte-for-byte."""
    raw = {"content": "Figure 3: pageNumber is not a key here"}
    out = normalize_adi_dict(raw)
    assert out["content"] == "Figure 3: pageNumber is not a key here"


def test_polygons_preserved_exactly():
    poly = [0.6183, 0.5288, 2.4529, 0.5262, 2.4532, 0.7462]
    out = normalize_adi_dict({"boundingRegions": [{"polygon": poly}]})
    assert out["bounding_regions"][0]["polygon"] == poly


def test_idempotent_on_already_normalized_input():
    """Read-side normalization must be safe to apply to new artifacts."""
    raw = {"pages": [{"pageNumber": 2}]}
    once = normalize_adi_dict(raw)
    twice = normalize_adi_dict(once)
    assert once == twice


def test_empty_and_scalar_inputs():
    assert normalize_adi_dict({}) == {}
    assert normalize_adi_dict([]) == []
    assert normalize_adi_dict("text") == "text"
    assert normalize_adi_dict(None) is None


# ── The actual bug ────────────────────────────────────────────────────────


REAL_ADI_SHAPE = {
    "modelId": "prebuilt-layout",
    "apiVersion": "2024-11-30",
    "pages": [
        {"pageNumber": 1, "width": 8.5, "height": 11, "unit": "inch"},
        {"pageNumber": 2, "width": 8.5, "height": 11, "unit": "inch"},
        {"pageNumber": 7, "width": 8.5, "height": 11, "unit": "inch"},
    ],
    "paragraphs": [
        {"role": "title", "content": "On page 1",
         "boundingRegions": [{"pageNumber": 1, "polygon": [0.6, 0.5, 2.4, 0.7]}]},
        {"role": None, "content": "On page 7",
         "boundingRegions": [{"pageNumber": 7, "polygon": [0.6, 1.5, 2.4, 1.7]}]},
    ],
    "tables": [
        {
            "rowCount": 12,
            "columnCount": 7,
            "boundingRegions": [{"pageNumber": 2, "polygon": [0.6, 1.0, 2.4, 1.5]}],
            "cells": [
                {"kind": "columnHeader", "rowIndex": 0, "columnIndex": 0,
                 "columnSpan": 2, "content": "Header"},
                {"rowIndex": 1, "columnIndex": 0, "content": "Body"},
            ],
        }
    ],
}


def test_paragraph_page_numbers_resolve_to_real_pages():
    """The original bug: this lookup returned None, and `or 1` hid it."""
    out = normalize_adi_dict(REAL_ADI_SHAPE)

    pages = [
        (p.get("bounding_regions") or [{}])[0].get("page_number") or 1
        for p in out["paragraphs"]
    ]
    assert pages == [1, 7], "paragraph pages must not collapse to 1"


def test_table_page_number_resolves():
    out = normalize_adi_dict(REAL_ADI_SHAPE)
    table = out["tables"][0]
    pnum = (table.get("bounding_regions") or [{}])[0].get("page_number") or 1
    assert pnum == 2


def test_table_cell_indices_and_spans_resolve():
    """Header detection keys off row_index == 0; spans drive grid layout."""
    out = normalize_adi_dict(REAL_ADI_SHAPE)
    cells = out["tables"][0]["cells"]

    assert [c.get("row_index") for c in cells] == [0, 1]
    assert [c.get("column_index") for c in cells] == [0, 0]
    assert (cells[0].get("column_span") or 1) == 2
    assert (cells[1].get("column_span") or 1) == 1

    headers = [c for c in cells if c.get("row_index") == 0]
    assert len(headers) == 1


def test_page_dimensions_resolve():
    """step4a skips every figure when page dims come back 0."""
    out = normalize_adi_dict(REAL_ADI_SHAPE)
    page = next(p for p in out["pages"] if p.get("page_number") == 7)
    assert float(page.get("width") or 0.0) == 8.5
    assert float(page.get("height") or 0.0) == 11


def test_unnormalized_input_demonstrates_the_failure():
    """Guards the premise: without normalization the reads silently degrade."""
    pages = [
        (p.get("bounding_regions") or [{}])[0].get("page_number") or 1
        for p in REAL_ADI_SHAPE["paragraphs"]
    ]
    assert pages == [1, 1], "raw camelCase collapses every page to the default"
