"""
Step 3 — Confidence-based routing.

Reads adi-results.json from Blob Storage and decides which pages need
Mistral OCR (low confidence tables, complex structure, or figure-overlapping-table).
Writes routing.json.

All routing rules ported 1:1 from v1 step3-confidence-router.ts.
"""

from __future__ import annotations

import logging
import os

from shared.blob_client import download_json_artifact, upload_json_artifact
from shared.telemetry import timed_step
from models.types import AdiPageResult, FigureLocation, RoutingDecision, TableConfidence

logger = logging.getLogger(__name__)

TABLE_CONFIDENCE_THRESHOLD = 0.75


def _polygon_to_rect(polygon: list[float]) -> dict:
    xs = polygon[0::2]
    ys = polygon[1::2]
    return {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)}


def _overlaps(a: list[float], b: list[float]) -> bool:
    if not a or not b or len(a) < 4 or len(b) < 4:
        return False
    ra = _polygon_to_rect(a)
    rb = _polygon_to_rect(b)
    return (
        ra["min_x"] < rb["max_x"]
        and ra["max_x"] > rb["min_x"]
        and ra["min_y"] < rb["max_y"]
        and ra["max_y"] > rb["min_y"]
    )


def _figure_overlaps_table(figure: FigureLocation, tables: list[TableConfidence]) -> bool:
    return any(_overlaps(figure.polygon, t.polygon) for t in tables)


def step3_router_main(ctx: dict) -> dict:
    doc_id: str = ctx["doc_id"]
    run_id: str = ctx["run_id"]

    with timed_step("step3_router", doc_id, run_id):
        raw = download_json_artifact(doc_id, run_id, "adi-results.json")
        adi_results = [AdiPageResult.model_validate(r) for r in raw]

        # OCR_ENABLED=false → skip Mistral entirely, use ADI for all pages.
        # Set this when Mistral/Foundry subscription is unavailable.
        # Re-enable once the subscription issue is resolved.
        ocr_enabled = os.environ.get("OCR_ENABLED", "true").lower() != "false"
        ocr_figure_routing = os.environ.get("OCR_FIGURE_ROUTING", "true").lower() != "false"

        pages_for_ocr: list[int] = []
        adi_only_pages: list[int] = []
        low_conf_tables: list[TableConfidence] = []

        if not ocr_enabled:
            # ADI-only mode: all pages go through ADI, no Mistral calls
            adi_only_pages = [p.page_number for p in adi_results]
            low_conf_tables = [t for p in adi_results for t in p.tables if t.requires_ocr]
            logger.warning(
                "[step3] OCR_ENABLED=false — skipping Mistral for all %d page(s). "
                "%d table(s) would normally require OCR.",
                len(adi_results), len(low_conf_tables),
            )
        else:
            for page in adi_results:
                has_low_conf = any(t.requires_ocr for t in page.tables)
                has_figure_overlap = ocr_figure_routing and any(
                    _figure_overlaps_table(f, page.tables) for f in page.figures
                )
                if has_low_conf or has_figure_overlap:
                    pages_for_ocr.append(page.page_number)
                else:
                    adi_only_pages.append(page.page_number)
                low_conf_tables.extend(t for t in page.tables if t.requires_ocr)

        decision = RoutingDecision(
            doc_id=doc_id,
            total_pages=len(adi_results),
            pages_for_ocr=pages_for_ocr,
            adi_only_pages=adi_only_pages,
            low_confidence_tables=low_conf_tables,
        )

        upload_json_artifact(doc_id, run_id, "routing.json", decision.model_dump())

        logger.info(
            "[step3] doc_id=%s ocr_enabled=%s adi_only=%s ocr_pages=%s low_conf_tables=%d",
            doc_id, ocr_enabled, adi_only_pages, pages_for_ocr, len(low_conf_tables),
        )
        return decision.model_dump()
