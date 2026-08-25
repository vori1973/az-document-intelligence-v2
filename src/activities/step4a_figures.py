"""
Step 4A / 4B — Figure candidate extraction and deterministic qualification.

4A  Build one candidate record per ADI figure, crop the region out of the
    source PDF at print resolution, and store it as a PNG artifact so the
    vision step (4C) and any UI have real pixels to work with.

4B  Apply deterministic rules that drop obvious noise — page furniture,
    hairlines, separators, slivers — *before* any paid vision call, and
    attach routing signals for the ambiguous cases.

ADI remains the citation authority. Page numbers and bounding polygons are
copied from ADI unchanged; cropping only reads them, never rewrites them.

Rejections are deliberately conservative: a rule fires only when there is
strong evidence, because a false rejection silently removes retrievable
content while a false positive merely costs one vision call.
"""

from __future__ import annotations

import io
import logging
import os

import fitz  # PyMuPDF

from shared.adi_normalize import normalize_adi_dict
from shared.blob_client import (
    download_document,
    download_json_artifact,
    upload_artifact,
    upload_json_artifact,
)
from shared.telemetry import timed_step, track_metric
from models.types import AdiPageResult, FigureCandidate, FigureFeatures

logger = logging.getLogger(__name__)

# ── Thresholds (POC starting values — tune per document family) ───────────

HEADER_FOOTER_OVERLAP_THRESHOLD = float(
    os.environ.get("FIGURE_HEADER_FOOTER_OVERLAP_THRESHOLD", "0.30")
)
MIN_AREA_RATIO = float(os.environ.get("FIGURE_MIN_AREA_RATIO", "0.002"))
MAX_AREA_RATIO = float(os.environ.get("FIGURE_MAX_AREA_RATIO", "0.90"))
MAX_ASPECT_RATIO = float(os.environ.get("FIGURE_MAX_ASPECT_RATIO", "12.0"))
REPEAT_PAGE_THRESHOLD = int(os.environ.get("FIGURE_REPEAT_PAGE_THRESHOLD", "4"))
FURNITURE_AREA_CEILING = float(
    os.environ.get("FIGURE_FURNITURE_AREA_CEILING", "0.01")
)

CROP_DPI = int(os.environ.get("FIGURE_CROP_DPI", "200"))
CROP_PADDING_IN = float(os.environ.get("FIGURE_CROP_PADDING_IN", "0.06"))

# Words that mean "this graphic still matters" — safety icons and callouts
# are frequently tiny but carry the highest-value content. Matched only in
# text near the figure (see _has_reference), never page-wide.
REFERENCE_TERMS = (
    "figure", "fig.", "see ", "shown", "illustrat", "diagram",
    "warning", "caution", "danger", "note", "legend", "symbol",
)

# How far from the figure (inches) a referencing phrase still counts.
REFERENCE_PROXIMITY_IN = float(os.environ.get("FIGURE_REFERENCE_PROXIMITY_IN", "1.0"))

POINTS_PER_INCH = 72.0


# ── Geometry helpers ──────────────────────────────────────────────────────


def _polygon_bbox(polygon: list[float]) -> tuple[float, float, float, float] | None:
    """Convert an ADI polygon [x1,y1,x2,y2,...] into (x0, y0, x1, y1)."""
    if not polygon or len(polygon) < 4:
        return None
    xs = polygon[0::2]
    ys = polygon[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _overlap_ratio(
    box: tuple[float, float, float, float],
    other: tuple[float, float, float, float],
) -> float:
    """Fraction of `box` covered by `other`."""
    ax0, ay0, ax1, ay1 = box
    bx0, by0, bx1, by1 = other
    inter_w = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    inter_h = max(0.0, min(ay1, by1) - max(ay0, by0))
    box_area = max((ax1 - ax0) * (ay1 - ay0), 1e-9)
    return (inter_w * inter_h) / box_area


def _furniture_regions(adi_raw: dict, page_number: int) -> list[tuple]:
    """Bounding boxes of ADI page furniture (header / footer / page number)."""
    regions = []
    for para in (adi_raw.get("paragraphs") or []):
        if (para.get("role") or "") not in ("pageHeader", "pageFooter", "pageNumber"):
            continue
        for region in (para.get("bounding_regions") or []):
            if region.get("page_number") != page_number:
                continue
            bbox = _polygon_bbox(region.get("polygon") or [])
            if bbox:
                regions.append(bbox)
    return regions


def _page_dimensions(adi_raw: dict, page_number: int) -> tuple[float, float]:
    for page in (adi_raw.get("pages") or []):
        if page.get("page_number") == page_number:
            return float(page.get("width") or 0.0), float(page.get("height") or 0.0)
    return 0.0, 0.0


def _nearby_text(adi_raw: dict, page_number: int) -> str:
    """Page text kept as (bbox, lowercased content) for proximity checks."""
    parts = []
    for para in (adi_raw.get("paragraphs") or []):
        for region in (para.get("bounding_regions") or []):
            if region.get("page_number") != page_number:
                continue
            bbox = _polygon_bbox(region.get("polygon") or [])
            if bbox:
                parts.append((bbox, (para.get("content") or "").lower()))
    return parts


def _has_reference(caption: str | None, page_text, figure_bbox=None) -> bool:
    """Decide whether the document points at this figure.

    A caption is decisive. Absent one, we look for a figure-referencing term
    in text *near* the figure rather than anywhere on the page: words like
    "note", "see", and "figure" appear on nearly every page of a technical
    manual, so a page-wide match would veto essentially every geometric
    rejection and make the filter decorative.
    """
    if caption and caption.strip():
        return True
    if figure_bbox is None:
        return False

    fx0, fy0, fx1, fy1 = figure_bbox
    near_x0, near_y0 = fx0 - REFERENCE_PROXIMITY_IN, fy0 - REFERENCE_PROXIMITY_IN
    near_x1, near_y1 = fx1 + REFERENCE_PROXIMITY_IN, fy1 + REFERENCE_PROXIMITY_IN

    for (bx0, by0, bx1, by1), content in page_text:
        if bx1 < near_x0 or bx0 > near_x1 or by1 < near_y0 or by0 > near_y1:
            continue
        if any(term in content for term in REFERENCE_TERMS):
            return True
    return False


# ── 4B: deterministic qualification ───────────────────────────────────────


def _qualify(
    features: FigureFeatures,
    caption: str | None,
    has_reference: bool,
) -> tuple[str, str | None, list[str]]:
    """Return (status, rejection_reason, routing_signals).

    Every hard rejection requires a geometric trigger *and* the absence of a
    textual reference, so a captioned or referenced figure is never dropped.
    """
    signals: list[str] = []

    furniture_overlap = max(features.header_overlap_ratio, features.footer_overlap_ratio)
    if furniture_overlap >= HEADER_FOOTER_OVERLAP_THRESHOLD and not has_reference:
        return "rejected", "structural_noise", signals

    if (
        features.repeat_page_count > REPEAT_PAGE_THRESHOLD
        and features.area_ratio < FURNITURE_AREA_CEILING
        and not has_reference
    ):
        return "rejected", "repeated_furniture", signals

    if features.area_ratio < MIN_AREA_RATIO and not has_reference:
        return "rejected", "low_value_graphic", signals

    if (
        features.aspect_ratio > MAX_ASPECT_RATIO
        and features.area_ratio < FURNITURE_AREA_CEILING
        and not has_reference
    ):
        return "rejected", "decorative_geometry", signals

    # Surviving-but-uncertain cases become routing signals, not rejections.
    if not caption:
        signals.append("caption_missing")
    if features.area_ratio < MIN_AREA_RATIO:
        signals.append("small_figure_with_reference")
    if features.area_ratio > MAX_AREA_RATIO:
        signals.append("full_page_graphic")
    if furniture_overlap >= HEADER_FOOTER_OVERLAP_THRESHOLD:
        signals.append("furniture_overlap_with_reference")

    return "candidate", None, signals


# ── 4A: cropping ──────────────────────────────────────────────────────────


def _crop_figure(
    pdf: fitz.Document,
    page_number: int,
    bbox: tuple[float, float, float, float],
) -> bytes | None:
    """Render the figure region to PNG at CROP_DPI.

    ADI reports PDF geometry in inches; PyMuPDF works in points.
    """
    try:
        page = pdf[page_number - 1]
    except IndexError:
        logger.warning("[step4a] page %d outside PDF", page_number)
        return None

    x0, y0, x1, y1 = bbox
    rect = fitz.Rect(
        (x0 - CROP_PADDING_IN) * POINTS_PER_INCH,
        (y0 - CROP_PADDING_IN) * POINTS_PER_INCH,
        (x1 + CROP_PADDING_IN) * POINTS_PER_INCH,
        (y1 + CROP_PADDING_IN) * POINTS_PER_INCH,
    )
    rect = rect & page.rect  # clamp to the page
    if rect.is_empty or rect.width <= 1 or rect.height <= 1:
        return None

    pixmap = page.get_pixmap(clip=rect, dpi=CROP_DPI)
    return pixmap.tobytes("png")


# ── Main ──────────────────────────────────────────────────────────────────


def step4a_figures_main(ctx: dict) -> dict:
    doc_id: str = ctx["doc_id"]
    run_id: str = ctx["run_id"]
    blob_name: str = ctx["blob_name"]

    with timed_step("step4a_figures", doc_id, run_id):
        adi_raw = normalize_adi_dict(download_json_artifact(doc_id, run_id, "adi-raw.json"))
        adi_results_raw = download_json_artifact(doc_id, run_id, "adi-results.json")
        adi_results = [AdiPageResult.model_validate(r) for r in adi_results_raw]

        total_figures = sum(len(r.figures) for r in adi_results)
        page_count = len(adi_results)
        if total_figures == 0:
            upload_json_artifact(doc_id, run_id, "figures.json", [])
            upload_json_artifact(doc_id, run_id, "step4a-result.json", {
                "page_count": page_count,
                "figures_total": 0,
                "qualified": 0,
                "rejected": 0,
            })
            logger.info("[step4a] doc_id=%s no figures", doc_id)
            return {"figures_total": 0, "qualified": 0}

        pdf_bytes = download_document(blob_name)
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")

        candidates: list[FigureCandidate] = []
        pending_qualification: list[
            tuple[
                FigureCandidate,
                FigureFeatures,
                tuple[float, float, float, float],
                bool,
            ]
        ] = []
        pages_by_position_group: dict[str, set[int]] = {}
        rejected_by_reason: dict[str, int] = {}

        try:
            for page_result in adi_results:
                pnum = page_result.page_number
                page_w, page_h = _page_dimensions(adi_raw, pnum)
                furniture = _furniture_regions(adi_raw, pnum)
                page_text = _nearby_text(adi_raw, pnum)

                for fig in page_result.figures:
                    bbox = _polygon_bbox(fig.polygon)
                    if not bbox or page_w <= 0 or page_h <= 0:
                        continue

                    x0, y0, x1, y1 = bbox
                    width = max(x1 - x0, 1e-9)
                    height = max(y1 - y0, 1e-9)

                    features = FigureFeatures(
                        width_ratio=width / page_w,
                        height_ratio=height / page_h,
                        area_ratio=(width * height) / (page_w * page_h),
                        aspect_ratio=max(width, height) / min(width, height),
                        header_overlap_ratio=max(
                            (_overlap_ratio(bbox, f) for f in furniture), default=0.0
                        ) if furniture else 0.0,
                        footer_overlap_ratio=0.0,
                        normalized_position_group=(
                            f"{x0 / page_w:.2f}:{y0 / page_h:.2f}:"
                            f"{width / page_w:.2f}:{height / page_h:.2f}"
                        ),
                    )

                    has_ref = _has_reference(fig.caption, page_text, bbox)

                    candidate = FigureCandidate(
                        document_id=doc_id,
                        source_file=blob_name,
                        page=pnum,
                        figure_index=fig.figure_index,
                        figure_id=fig.figure_id,
                        bounding_polygon=fig.polygon,
                        caption=fig.caption,
                        page_width=page_w,
                        page_height=page_h,
                        features=features,
                    )
                    candidates.append(candidate)
                    pending_qualification.append((candidate, features, bbox, has_ref))
                    pages_by_position_group.setdefault(
                        features.normalized_position_group, set()
                    ).add(pnum)

            for candidate, features, bbox, has_ref in pending_qualification:
                features.repeat_page_count = len(
                    pages_by_position_group[features.normalized_position_group]
                )
                status, reason, signals = _qualify(
                    features, candidate.caption, has_ref
                )
                candidate.status = status
                candidate.rejection_reason = reason
                candidate.routing_signals = signals

                if status == "rejected":
                    rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
                else:
                    png = _crop_figure(pdf, candidate.page, bbox)
                    if png:
                        filename = (
                            f"figures/p{candidate.page}-fig"
                            f"{candidate.figure_index}.png"
                        )
                        upload_artifact(doc_id, run_id, filename, png)
                        candidate.tight_crop_uri = filename
                    else:
                        candidate.status = "rejected"
                        candidate.rejection_reason = "crop_failed"
                        rejected_by_reason["crop_failed"] = (
                            rejected_by_reason.get("crop_failed", 0) + 1
                        )
        finally:
            pdf.close()

        qualified = [c for c in candidates if c.status == "candidate"]

        upload_json_artifact(
            doc_id, run_id, "figures.json", [c.model_dump() for c in candidates]
        )
        upload_json_artifact(doc_id, run_id, "step4a-result.json", {
            "page_count": page_count,
            "figures_total": len(candidates),
            "qualified": len(qualified),
            "rejected": len(candidates) - len(qualified),
            "rejected_by_reason": rejected_by_reason,
        })

        track_metric("figures_total", len(candidates), doc_id=doc_id)
        track_metric("figures_qualified", len(qualified), doc_id=doc_id)

        logger.info(
            "[step4a] doc_id=%s figures=%d qualified=%d rejected=%s",
            doc_id, len(candidates), len(qualified), rejected_by_reason or "{}",
        )
        return {"figures_total": len(candidates), "qualified": len(qualified)}
