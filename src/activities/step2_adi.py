"""
Step 2 — Azure Document Intelligence (ADI).

Sends the PDF to ADI prebuilt-layout model with markdown output.
Builds per-page TableConfidence (span-matched word confidence scoring),
extracts FigureLocations and BoundingBoxes.
Writes adi-raw.json and adi-content.md to Blob Storage.

Auth: DefaultAzureCredential — Function App MI must have
      Cognitive Services User on the ADI resource.

Ported from v1 step2-adi.ts.
"""

from __future__ import annotations

import logging
import os
import time

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

from shared.auth import get_credential
from shared.blob_client import download_document, upload_artifact, upload_json_artifact
from shared.telemetry import timed_step, track_metric
from models.types import AdiPageResult, BoundingBox, FigureLocation, TableConfidence

logger = logging.getLogger(__name__)

TABLE_CONFIDENCE_THRESHOLD = 0.75
ADI_MODEL = os.environ.get("ADI_MODEL", "prebuilt-layout")
ADI_ENDPOINT = os.environ.get("ADI_ENDPOINT", "")


def _get_client() -> DocumentIntelligenceClient:
    return DocumentIntelligenceClient(
        endpoint=ADI_ENDPOINT,
        credential=get_credential(),
    )


# ── Word confidence index ─────────────────────────────────────────────────


def _build_word_index(pages: list) -> list[dict]:
    index = []
    for page in pages:
        for word in (page.words or []):
            index.append({
                "confidence": word.confidence,
                "offset": word.span.offset,
                "end": word.span.offset + word.span.length,
            })
    return index


def _cell_word_confidences(cell, word_index: list[dict]) -> list[float]:
    confs = []
    for span in (cell.spans or []):
        start, end = span.offset, span.offset + span.length
        for w in word_index:
            if w["offset"] >= start and w["end"] <= end:
                confs.append(w["confidence"])
    return confs


# ── Table confidence ──────────────────────────────────────────────────────


def _build_table_confidence(
    table, page_number: int, table_index: int, word_index: list[dict], page_angle: float
) -> TableConfidence:
    per_cell_avgs = []
    unmatched_cells = 0

    for cell in table.cells:
        word_confs = _cell_word_confidences(cell, word_index)
        if not word_confs:
            if (cell.content or "").strip():
                unmatched_cells += 1
            continue
        per_cell_avgs.append(sum(word_confs) / len(word_confs))

    avg = sum(per_cell_avgs) / len(per_cell_avgs) if per_cell_avgs else 1.0
    min_conf = min(per_cell_avgs) if per_cell_avgs else 1.0
    polygon = (table.bounding_regions[0].polygon if table.bounding_regions else [])

    complexity_reasons: list[str] = []

    # rowSpan > 1 on body cells → merged rows
    row_span_cells = [
        c for c in table.cells
        if (c.row_span or 1) > 1 and c.kind != "columnHeader"
    ]
    if row_span_cells:
        complexity_reasons.append(f"rowSpan>1 on {len(row_span_cells)} cell(s)")

    page_is_upright = abs(page_angle) < 45

    # Rotated cells (h/w > 5 with non-trivial text on upright page)
    rotated_cells = []
    if page_is_upright:
        for c in table.cells:
            poly = (c.bounding_regions[0].polygon if c.bounding_regions else [])
            if len(poly) < 8:
                continue
            xs = poly[0::2]
            ys = poly[1::2]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            if w > 0 and h / w > 5 and len((c.content or "").strip()) > 3:
                rotated_cells.append(c)
    if rotated_cells:
        complexity_reasons.append(f"rotated cells ({len(rotated_cells)} cell(s) with h/w>5)")

    # Paragraph-length cells (> 500 chars)
    paragraph_cells = [c for c in table.cells if len((c.content or "").strip()) > 500]
    if paragraph_cells:
        complexity_reasons.append(f"paragraph-length cells ({len(paragraph_cells)} cell(s) >500 chars)")

    # Extreme column width disparity (>10:1 ratio with max > 3 inches)
    col_widths: dict[int, float] = {}
    for c in table.cells:
        poly = (c.bounding_regions[0].polygon if c.bounding_regions else [])
        if len(poly) < 8:
            continue
        xs = poly[0::2]
        w = max(xs) - min(xs)
        col = c.column_index or 0
        col_widths[col] = max(col_widths.get(col, 0), w)
    if len(col_widths) > 1:
        max_w = max(col_widths.values())
        min_w = min(col_widths.values())
        if min_w > 0 and max_w / min_w > 10 and max_w > 3.0:
            complexity_reasons.append(f"column width disparity ({max_w/min_w:.0f}:1 ratio)")

    has_complex = bool(complexity_reasons)
    requires_ocr = min_conf < TABLE_CONFIDENCE_THRESHOLD or has_complex

    return TableConfidence(
        table_index=table_index,
        page_number=page_number,
        average_cell_confidence=avg,
        min_cell_confidence=min_conf,
        cell_count=len(table.cells),
        unmatched_cells=unmatched_cells,
        requires_ocr=requires_ocr,
        has_complex_structure=has_complex,
        complexity_reasons=complexity_reasons,
        polygon=polygon,
    )


def _extract_figures(result, page_number: int) -> list[FigureLocation]:
    figures = []
    for i, fig in enumerate(result.get("figures", [])):
        region = next(
            (r for r in (fig.get("bounding_regions") or []) if r.get("page_number") == page_number),
            None,
        )
        if not region:
            continue
        figures.append(FigureLocation(
            figure_index=i,
            figure_id=fig.get("id") or f"fig-{i}",
            page_number=page_number,
            polygon=region.get("polygon") or [],
            caption=(fig.get("caption") or {}).get("content"),
        ))
    return figures


def _extract_bounding_boxes(result, page_number: int) -> list[BoundingBox]:
    boxes = []
    for para in (result.get("paragraphs") or []):
        for region in (para.get("bounding_regions") or []):
            if region.get("page_number") == page_number:
                boxes.append(BoundingBox(
                    page_number=page_number,
                    role=para.get("role") or "paragraph",
                    content=para.get("content") or "",
                    polygon=region.get("polygon") or [],
                ))
    return boxes


# ── Main ──────────────────────────────────────────────────────────────────


def step2_adi_main(ctx: dict) -> dict:
    doc_id: str = ctx["doc_id"]
    run_id: str = ctx["run_id"]
    blob_name: str = ctx["blob_name"]

    with timed_step("step2_adi", doc_id, run_id):
        pdf_bytes = download_document(blob_name)
        client = _get_client()

        t0 = time.monotonic()
        poller = client.begin_analyze_document(
            ADI_MODEL,
            AnalyzeDocumentRequest(bytes_source=pdf_bytes),
            output_content_format="markdown",
            output=["figures"],
        )
        result = poller.result()
        duration_ms = (time.monotonic() - t0) * 1000

        # Serialize result to dict for artifact storage
        result_dict = result.as_dict() if hasattr(result, "as_dict") else dict(result)

        pages = result_dict.get("pages") or []
        tables = result_dict.get("tables") or []
        figures_raw = result_dict.get("figures") or []

        word_index = _build_word_index(result.pages or [])

        # Group tables by page
        tables_by_page: dict[int, list] = {}
        for t in (result.tables or []):
            pnum = (t.bounding_regions[0].page_number if t.bounding_regions else 1)
            tables_by_page.setdefault(pnum, []).append(t)

        adi_results: list[AdiPageResult] = []
        for page in (result.pages or []):
            pnum = page.page_number
            page_angle = getattr(page, "angle", 0.0) or 0.0
            page_tables = tables_by_page.get(pnum, [])
            table_confidences = [
                _build_table_confidence(t, pnum, i, word_index, page_angle)
                for i, t in enumerate(page_tables)
            ]
            figures = _extract_figures(result_dict, pnum)
            bboxes = _extract_bounding_boxes(result_dict, pnum)
            raw_content = "\n".join(
                p.get("content", "") for p in (result_dict.get("paragraphs") or [])
                if any(r.get("page_number") == pnum for r in (p.get("bounding_regions") or []))
            )
            adi_results.append(AdiPageResult(
                page_number=pnum,
                tables=table_confidences,
                figures=figures,
                raw_content=raw_content,
                bounding_boxes=bboxes,
            ))

        # Persist artifacts
        upload_json_artifact(doc_id, run_id, "adi-raw.json", result_dict)
        if result.content:
            upload_artifact(doc_id, run_id, "adi-content.md", result.content)
        upload_json_artifact(
            doc_id, run_id, "adi-results.json",
            [r.model_dump() for r in adi_results]
        )

        track_metric("adi_pages", len(pages), doc_id=doc_id)
        track_metric("adi_tables", len(tables), doc_id=doc_id)
        track_metric("adi_figures", len(figures_raw), doc_id=doc_id)

        low_conf = sum(1 for r in adi_results for t in r.tables if t.requires_ocr)
        logger.info(
            "[step2] doc_id=%s pages=%d tables=%d figures=%d low_conf=%d %.0fms",
            doc_id, len(pages), len(tables), len(figures_raw), low_conf, duration_ms,
        )
        upload_json_artifact(doc_id, run_id, "step2-result.json", {
            "pages": len(pages),
            "tables": len(tables),
            "figures": len(figures_raw),
            "low_conf_pages": low_conf,
            "duration_ms": round(duration_ms),
        })
        return {"adi_pages": len(pages), "tables": len(tables)}
