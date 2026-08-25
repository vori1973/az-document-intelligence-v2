"""
Unit tests for figure chunk composition in step5_chunks.py.

Covers both the enriched path (vision understanding available) and the
fallback path (caption only), plus the drop rules that keep rejected
figures out of the index.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from activities.step5_chunks import _build_figure_chunks, _figure_text as _figure_text_raw
from models.types import AdiPageResult, FigureLocation

DOC_ID = "doc-1"
BLOB = "source.pdf"
RUN_ID = "run-1"


def _figure_text(fig, record):
    return _figure_text_raw(fig.caption, fig.page_number, record)


def _figure(
    figure_index: int = 0,
    page_number: int = 7,
    caption: str | None = "Figure 3. Handpiece",
    adi_image_blob: str | None = None,
) -> FigureLocation:
    return FigureLocation(
        figure_index=figure_index,
        figure_id=f"p{page_number}_fig{figure_index}",
        page_number=page_number,
        polygon=[1.0, 1.0, 3.0, 1.0, 3.0, 3.0, 1.0, 3.0],
        caption=caption,
        adi_image_blob=adi_image_blob,
    )


def _page(*figures: FigureLocation) -> AdiPageResult:
    page_number = figures[0].page_number if figures else 1
    return AdiPageResult(page_number=page_number, figures=list(figures))


def _understanding_record(
    page: int = 7,
    figure_index: int = 0,
    routing_outcome: str = "retain",
    understanding: dict | None = None,
    tight_crop_uri: str | None = "figures/p7-fig0.png",
) -> dict:
    return {
        "page": page,
        "figure_index": figure_index,
        "routing_outcome": routing_outcome,
        "tight_crop_uri": tight_crop_uri,
        "understanding": understanding,
    }


FULL_UNDERSTANDING = {
    "is_meaningful": True,
    "category": "device_component",
    "model_confidence_label": "high",
    "short_description": "A handpiece aligned with its connection port.",
    "visible_labels": ["Release control", "Connection port"],
    "device_or_component_terms": ["handpiece"],
    "procedure_actions": ["align and lock the handpiece"],
    "warnings_or_constraints": ["Do not force the connector"],
    "search_keywords": ["handpiece attachment", "connection port"],
    "uncertainty": [],
    "needs_larger_context_crop": False,
}


# ── _figure_text — fallback path ──────────────────────────────────────────


class TestFigureTextFallback:
    def test_caption_only_when_no_record(self):
        assert _figure_text(_figure(), None) == "[Figure] Figure 3. Handpiece (Page 7)"

    def test_caption_only_when_record_has_no_understanding(self):
        record = _understanding_record(understanding=None)
        assert _figure_text(_figure(), record) == "[Figure] Figure 3. Handpiece (Page 7)"

    def test_missing_caption_still_carries_page(self):
        text = _figure_text(_figure(caption=None), None)
        assert "[Figure]" in text
        assert "(Page 7)" in text

    def test_empty_understanding_dict_falls_back(self):
        record = _understanding_record(understanding={})
        assert _figure_text(_figure(), record) == "[Figure] Figure 3. Handpiece (Page 7)"


# ── _figure_text — enriched path ──────────────────────────────────────────


class TestFigureTextEnriched:
    def test_includes_caption_and_description(self):
        text = _figure_text(_figure(), _understanding_record(understanding=FULL_UNDERSTANDING))
        assert "Figure 3. Handpiece" in text
        assert "A handpiece aligned with its connection port." in text

    def test_includes_all_enrichment_fields(self):
        text = _figure_text(_figure(), _understanding_record(understanding=FULL_UNDERSTANDING))
        assert "Visible Labels: Release control, Connection port" in text
        assert "Device Or Component Terms: handpiece" in text
        assert "Procedure Actions: align and lock the handpiece" in text
        assert "Warnings Or Constraints: Do not force the connector" in text
        assert "Search Keywords: handpiece attachment, connection port" in text

    def test_includes_category_and_page(self):
        text = _figure_text(_figure(), _understanding_record(understanding=FULL_UNDERSTANDING))
        assert "Category: device_component" in text
        assert text.endswith("(Page 7)")

    def test_unknown_category_is_omitted(self):
        understanding = {**FULL_UNDERSTANDING, "category": "unknown"}
        text = _figure_text(_figure(), _understanding_record(understanding=understanding))
        assert "Category:" not in text

    def test_empty_lists_are_omitted(self):
        understanding = {
            "short_description": "A schematic.",
            "category": "diagram",
            "visible_labels": [],
            "device_or_component_terms": ["  ", ""],
            "procedure_actions": [],
            "warnings_or_constraints": [],
            "search_keywords": [],
        }
        text = _figure_text(_figure(), _understanding_record(understanding=understanding))
        assert "Visible Labels" not in text
        assert "Device Or Component Terms" not in text
        assert "A schematic." in text

    def test_enrichment_works_without_a_caption(self):
        text = _figure_text(
            _figure(caption=None), _understanding_record(understanding=FULL_UNDERSTANDING)
        )
        assert "A handpiece aligned with its connection port." in text
        assert text.startswith("[Figure]")

    def test_enriched_text_is_longer_than_caption_only(self):
        fig = _figure()
        enriched = _figure_text(fig, _understanding_record(understanding=FULL_UNDERSTANDING))
        assert len(enriched) > len(_figure_text(fig, None))


# ── _build_figure_chunks — drop rules ─────────────────────────────────────


class TestBuildFigureChunksDropRules:
    def test_indexes_all_figures_without_artifacts(self):
        chunks = _build_figure_chunks([_page(_figure())], DOC_ID, BLOB, RUN_ID)
        assert len(chunks) == 1
        assert chunks[0].type == "figure"

    def test_deterministic_rejection_drops_the_chunk(self):
        candidates = [{"page": 7, "figure_index": 0, "status": "rejected", "rejection_reason": "structural_noise"}]
        chunks = _build_figure_chunks(
            [_page(_figure())], DOC_ID, BLOB, RUN_ID, None, candidates
        )
        assert chunks == []

    def test_confident_vision_rejection_drops_the_chunk(self):
        records = {(7, 0): _understanding_record(routing_outcome="reject")}
        chunks = _build_figure_chunks([_page(_figure())], DOC_ID, BLOB, RUN_ID, records)
        assert chunks == []

    def test_low_confidence_outcomes_are_retained(self):
        for outcome in ("retain", "retain_low_confidence", "retain_unverified"):
            records = {(7, 0): _understanding_record(routing_outcome=outcome)}
            chunks = _build_figure_chunks([_page(_figure())], DOC_ID, BLOB, RUN_ID, records)
            assert len(chunks) == 1, outcome

    def test_candidate_without_description_or_caption_is_not_indexed(self):
        candidates = [{"page": 7, "figure_index": 0, "status": "candidate"}]
        chunks = _build_figure_chunks(
            [_page(_figure(caption=None))], DOC_ID, BLOB, RUN_ID, None, candidates
        )
        assert chunks == []

    def test_caption_only_candidate_is_indexed(self):
        candidates = [{
            "page": 7, "figure_index": 0, "status": "candidate",
            "caption": "Figure 3. Handpiece",
        }]
        chunks = _build_figure_chunks(
            [_page(_figure(caption="Figure 3. Handpiece"))],
            DOC_ID,
            BLOB,
            RUN_ID,
            None,
            candidates,
        )
        assert len(chunks) == 1
        assert "Figure 3. Handpiece" in chunks[0].text_for_embedding

    def test_description_without_caption_is_indexed(self):
        candidates = [{"page": 7, "figure_index": 0, "status": "candidate"}]
        records = {(7, 0): _understanding_record(understanding=FULL_UNDERSTANDING)}
        chunks = _build_figure_chunks(
            [_page(_figure(caption=None))],
            DOC_ID,
            BLOB,
            RUN_ID,
            records,
            candidates,
        )
        assert len(chunks) == 1


# ── _build_figure_chunks — citation and image references ──────────────────


class TestBuildFigureChunksReferences:
    def test_citation_comes_from_adi(self):
        fig = _figure()
        records = {(7, 0): _understanding_record(understanding=FULL_UNDERSTANDING)}
        chunk = _build_figure_chunks([_page(fig)], DOC_ID, BLOB, RUN_ID, records)[0]
        assert chunk.citation.page == 7
        assert chunk.citation.figure_index == 0
        assert chunk.citation.bounding_polygon == fig.polygon
        assert chunk.citation.document_id == DOC_ID

    def test_tight_crop_uri_is_preferred(self):
        records = {(7, 0): _understanding_record(tight_crop_uri="figures/p7-fig0.png")}
        chunk = _build_figure_chunks(
            [_page(_figure(adi_image_blob="p7-adi-fig-0.jpeg"))],
            DOC_ID, BLOB, RUN_ID, records,
        )[0]
        assert chunk.image_blob == "figures/p7-fig0.png"

    def test_candidate_crop_used_when_record_has_none(self):
        candidates = [{
            "page": 7, "figure_index": 0, "status": "candidate",
            "tight_crop_uri": "figures/p7-fig0.png",
            "caption": "Figure 3. Handpiece",
        }]
        chunk = _build_figure_chunks(
            [_page(_figure())], DOC_ID, BLOB, RUN_ID, None, candidates
        )[0]
        assert chunk.image_blob == "figures/p7-fig0.png"

    def test_falls_back_to_adi_image_blob(self):
        chunk = _build_figure_chunks(
            [_page(_figure(adi_image_blob="p7-adi-fig-0.jpeg"))], DOC_ID, BLOB, RUN_ID
        )[0]
        assert chunk.image_blob == "p7-adi-fig-0.jpeg"

    def test_chunk_ids_are_stable_and_unique(self):
        page = _page(_figure(figure_index=0), _figure(figure_index=1))
        first = _build_figure_chunks([page], DOC_ID, BLOB, RUN_ID)
        second = _build_figure_chunks([page], DOC_ID, BLOB, RUN_ID)
        ids = [c.chunk_id for c in first]
        assert len(set(ids)) == 2
        assert ids == [c.chunk_id for c in second]

    def test_enriched_text_reaches_the_chunk(self):
        records = {(7, 0): _understanding_record(understanding=FULL_UNDERSTANDING)}
        chunk = _build_figure_chunks([_page(_figure())], DOC_ID, BLOB, RUN_ID, records)[0]
        assert "handpiece" in chunk.text_for_embedding.lower()
        assert "Connection port" in chunk.text_for_embedding
