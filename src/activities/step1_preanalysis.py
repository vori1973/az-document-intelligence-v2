"""
Step 1 — Pre-analysis.

Downloads the PDF from Blob Storage, computes SHA-256 → doc_id,
extracts page count and text-vs-scanned heuristic using PyMuPDF.
Writes step1-result.json to processing/{doc_id}/{run_id}/.

Ported from v1 step1-preanalysis.ts.
"""

from __future__ import annotations

import hashlib
import logging
import os

import fitz  # PyMuPDF

from shared.blob_client import download_document, upload_json_artifact
from shared.telemetry import timed_step
from models.types import ImagePlacement, PageImageClassification, PreAnalysisResult

logger = logging.getLogger(__name__)

# Image coverage ratio above which a page is treated as scanned (one
# full-page raster, structurally indistinguishable from a deliberate
# full-bleed image) and skipped by the recovery cross-check in step 4A.
FIGURE_SCANNED_PAGE_COVERAGE_THRESHOLD = float(
    os.environ.get("FIGURE_SCANNED_PAGE_COVERAGE_THRESHOLD", "0.85")
)


def _is_cross_check_eligible(coverage_ratio: float, enumerable: bool) -> bool:
    """Whether a page is eligible for step 4A's recovery cross-check.

    A page whose embedded images collectively cover substantially the whole
    page is treated as scanned — one full-page raster, structurally
    indistinguishable from a deliberate full-bleed image — and is skipped.
    """
    return enumerable and coverage_ratio < FIGURE_SCANNED_PAGE_COVERAGE_THRESHOLD


def _enumerate_page_placements(
    doc: fitz.Document, page_index: int
) -> tuple[list[ImagePlacement], float, bool]:
    """Embedded raster image placements for one page, independent of ADI.

    Returns (placements, image_coverage_ratio, enumerable). Enumeration
    failure on a single page must not fail the whole run — the page is
    reported as not enumerable and processing continues.
    """
    page_number = page_index + 1
    try:
        page = doc[page_index]
        page_rect = page.rect
        page_area = max(page_rect.width * page_rect.height, 1e-9)

        placements: list[ImagePlacement] = []
        covered_area = 0.0
        for image in page.get_images(full=True):
            xref = image[0]
            width_px, height_px = image[2], image[3]
            for rect in page.get_image_rects(xref):
                clipped = rect & page_rect
                if clipped.is_empty:
                    continue
                placements.append(ImagePlacement(
                    page_number=page_number,
                    rect=[clipped.x0, clipped.y0, clipped.x1, clipped.y1],
                    width_px=width_px,
                    height_px=height_px,
                ))
                covered_area += clipped.width * clipped.height

        coverage_ratio = min(covered_area / page_area, 1.0)
        return placements, coverage_ratio, True
    except Exception:
        logger.warning(
            "[step1] failed to enumerate image placements on page %d", page_number,
            exc_info=True,
        )
        return [], 0.0, False


def step1_preanalysis_main(ctx: dict) -> dict:
    doc_id: str = ctx["doc_id"]
    run_id: str = ctx["run_id"]
    blob_name: str = ctx["blob_name"]

    with timed_step("step1_preanalysis", doc_id, run_id, blob_name=blob_name):
        pdf_bytes = download_document(blob_name)
        file_size_bytes = len(pdf_bytes)

        # Verify SHA-256 matches the doc_id assigned by ingest_trigger
        computed_id = hashlib.sha256(pdf_bytes).hexdigest()[:16]
        assert computed_id == doc_id, f"doc_id mismatch: {computed_id} != {doc_id}"

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_count = doc.page_count

        # Heuristic: average extracted text chars per page.
        # < 50 chars/page → scanned/image-only PDF
        page_char_counts = [len(doc[i].get_text()) for i in range(page_count)]
        total_chars = sum(page_char_counts)
        avg_chars = total_chars / max(page_count, 1)
        has_text = avg_chars > 50

        # Per-page classification and embedded image placements, enumerated
        # independently of ADI (add-missed-figure-detection). Persisted here
        # so step 4A can consume them without reopening the PDF.
        all_placements: list[ImagePlacement] = []
        pages: list[PageImageClassification] = []
        for i in range(page_count):
            page_number = i + 1
            page_has_text = page_char_counts[i] > 50
            placements, coverage_ratio, enumerable = _enumerate_page_placements(doc, i)
            all_placements.extend(placements)
            pages.append(PageImageClassification(
                page_number=page_number,
                has_text=page_has_text,
                image_coverage_ratio=coverage_ratio,
                cross_check_eligible=_is_cross_check_eligible(coverage_ratio, enumerable),
                enumerable=enumerable,
            ))
        doc.close()

        result = PreAnalysisResult(
            blob_name=blob_name,
            doc_id=doc_id,
            page_count=page_count,
            has_text=has_text,
            file_size_bytes=file_size_bytes,
            pages=pages,
        )

        upload_json_artifact(doc_id, run_id, "step1-result.json", result.model_dump())
        upload_json_artifact(
            doc_id, run_id, "image-placements.json",
            [p.model_dump() for p in all_placements],
        )

        logger.info(
            "[step1] doc_id=%s pages=%d has_text=%s size=%.1fKB avg_chars/page=%.0f",
            doc_id, page_count, has_text, file_size_bytes / 1024, avg_chars,
        )
        return result.model_dump()
