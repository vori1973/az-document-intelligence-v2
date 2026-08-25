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
from models.types import (
    AdiPageResult,
    FigureCandidate,
    FigureFeatures,
    ImagePlacement,
    PageImageClassification,
)

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

# Recovery cross-check (add-missed-figure-detection): recovers figures the
# document reader missed by enumerating the PDF's own embedded image
# placements (step 1) and cross-checking them against ADI's polygons.
FIGURE_RECOVERY_ENABLED = os.environ.get("FIGURE_RECOVERY_ENABLED", "false").lower() == "true"
FIGURE_RECOVERY_OVERLAP_THRESHOLD = float(
    os.environ.get("FIGURE_RECOVERY_OVERLAP_THRESHOLD", "0.30")
)

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


def _placement_rect_to_inches(
    rect: list[float],
) -> tuple[float, float, float, float] | None:
    """Convert a PDF placement rectangle from points (PyMuPDF) to inches
    (ADI's coordinate space).
    """
    if not rect or len(rect) != 4:
        return None
    x0, y0, x1, y1 = rect
    return (
        x0 / POINTS_PER_INCH, y0 / POINTS_PER_INCH,
        x1 / POINTS_PER_INCH, y1 / POINTS_PER_INCH,
    )


def _bbox_to_polygon(bbox: tuple[float, float, float, float]) -> list[float]:
    """Axis-aligned bbox -> flat 4-corner polygon in ADI's [x1,y1,x2,y2,...] form."""
    x0, y0, x1, y1 = bbox
    return [x0, y0, x1, y0, x1, y1, x0, y1]


def _already_detected(
    bbox: tuple[float, float, float, float],
    existing_bboxes: list[tuple[float, float, float, float]],
    threshold: float,
) -> bool:
    """Whether `bbox` substantially overlaps any already-detected figure.

    Checked in both directions since ADI polygons and PDF placement
    rectangles are rarely the same size — a placement fully inside a larger
    ADI region, or vice versa, both count as "already detected".
    """
    for other in existing_bboxes:
        if max(_overlap_ratio(bbox, other), _overlap_ratio(other, bbox)) >= threshold:
            return True
    return False


def _first_recovered_index(max_adi_figure_index: int) -> int:
    """First figure index guaranteed not to collide with any ADI-assigned
    index. ADI's own indices are never renumbered; recovered figures start
    strictly above the highest one seen.
    """
    return max_adi_figure_index + 1


def _candidate_features(
    bbox: tuple[float, float, float, float],
    page_w: float,
    page_h: float,
    furniture: list[tuple],
) -> FigureFeatures:
    """Geometric features shared by reader-detected and recovered figures."""
    x0, y0, x1, y1 = bbox
    width = max(x1 - x0, 1e-9)
    height = max(y1 - y0, 1e-9)
    return FigureFeatures(
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


def _load_recovery_inputs(
    doc_id: str, run_id: str
) -> tuple[dict[int, PageImageClassification], dict[int, list[ImagePlacement]]] | tuple[None, None]:
    """Per-page classification and image placements written by step 1.

    Returns (None, None) when recovery inputs are unavailable — an older run,
    or step 1 predates this capability — so the caller falls back to
    reader-only behavior rather than failing.
    """
    try:
        step1_raw = download_json_artifact(doc_id, run_id, "step1-result.json")
        placements_raw = download_json_artifact(doc_id, run_id, "image-placements.json")
    except Exception:
        logger.info(
            "[step4a] doc_id=%s recovery inputs unavailable; reader-only", doc_id
        )
        return None, None

    pages_by_number = {
        p["page_number"]: PageImageClassification.model_validate(p)
        for p in (step1_raw.get("pages") or [])
    }
    placements_by_page: dict[int, list[ImagePlacement]] = {}
    for raw in placements_raw:
        placement = ImagePlacement.model_validate(raw)
        placements_by_page.setdefault(placement.page_number, []).append(placement)
    return pages_by_number, placements_by_page


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
    """Page text kept as (bbox, original-case content) for proximity checks.

    Case is preserved here (rather than lowercased as before) because this
    same text is now also carried onto the candidate as document context for
    the vision prompt; `_has_reference` lowercases locally when matching.
    """
    parts = []
    for para in (adi_raw.get("paragraphs") or []):
        for region in (para.get("bounding_regions") or []):
            if region.get("page_number") != page_number:
                continue
            bbox = _polygon_bbox(region.get("polygon") or [])
            if bbox:
                parts.append((bbox, (para.get("content") or "")))
    return parts


def _nearby_paragraphs(page_text, figure_bbox):
    """Paragraphs within REFERENCE_PROXIMITY_IN of the figure, in reading order."""
    if figure_bbox is None:
        return []

    fx0, fy0, fx1, fy1 = figure_bbox
    near_x0, near_y0 = fx0 - REFERENCE_PROXIMITY_IN, fy0 - REFERENCE_PROXIMITY_IN
    near_x1, near_y1 = fx1 + REFERENCE_PROXIMITY_IN, fy1 + REFERENCE_PROXIMITY_IN

    nearby = []
    for bbox, content in page_text:
        bx0, by0, bx1, by1 = bbox
        if bx1 < near_x0 or bx0 > near_x1 or by1 < near_y0 or by0 > near_y1:
            continue
        nearby.append((bbox, content))
    nearby.sort(key=lambda item: (item[0][1], item[0][0]))
    return nearby


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
    for _, content in _nearby_paragraphs(page_text, figure_bbox):
        if any(term in content.lower() for term in REFERENCE_TERMS):
            return True
    return False


def _recovered_candidate_has_reference() -> bool:
    """Whether a recovered candidate qualifies for the has_reference escape
    hatch in `_qualify` (structural_noise, repeated_furniture,
    low_value_graphic, decorative_geometry).

    Always False. Recovered candidates never carry a real ADI caption, so
    `_has_reference`'s only route for them would be its proximity-text
    fallback -- and on dense pages (e.g. marketing catalogs) a generic term
    like "note" or "figure" is almost always within a paragraph of *any*
    tiny inline glyph. That defeats MIN_AREA_RATIO for exactly the
    sub-pixel icon/emoji fragments it exists to reject, so recovered
    candidates rely solely on geometry.
    """
    return False


def _nearby_text_context(page_text, figure_bbox) -> str | None:
    """Text near the figure, joined in reading order, for document context.

    Returns None (rather than an empty string) when nothing is nearby, so
    candidates without located context degrade cleanly instead of carrying
    an empty-but-present field.
    """
    parts = [content.strip() for _, content in _nearby_paragraphs(page_text, figure_bbox) if content.strip()]
    return " ".join(parts) if parts else None


def _section_headings(adi_raw: dict) -> list[tuple[int, float, str]]:
    """(page_number, y0, heading text) for every sectionHeading paragraph.

    Sorted in document reading order so the heading in force at a given
    figure is the last one at or before its position.
    """
    headings = []
    for para in (adi_raw.get("paragraphs") or []):
        if (para.get("role") or "") != "sectionHeading":
            continue
        content = (para.get("content") or "").strip()
        if not content:
            continue
        for region in (para.get("bounding_regions") or []):
            bbox = _polygon_bbox(region.get("polygon") or [])
            pnum = region.get("page_number")
            if bbox and pnum is not None:
                headings.append((pnum, bbox[1], content))
    headings.sort(key=lambda h: (h[0], h[1]))
    return headings


def _section_heading_for(
    headings: list[tuple[int, float, str]], page_number: int, figure_y0: float
) -> str | None:
    """The most recent section heading at or before this figure's position."""
    current = None
    for pnum, y0, text in headings:
        if pnum > page_number or (pnum == page_number and y0 > figure_y0):
            break
        current = text
    return current


def _document_title(adi_raw: dict, source_file: str) -> str:
    """The ADI-detected document title, falling back to the source filename."""
    for para in (adi_raw.get("paragraphs") or []):
        if (para.get("role") or "") == "title":
            content = (para.get("content") or "").strip()
            if content:
                return content
    return os.path.basename(source_file)


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

        # A document-level "no figures" short-circuit is only safe when
        # recovery is disabled — with it enabled, a page with zero
        # ADI-reported figures is exactly the case recovery exists for.
        if total_figures == 0 and not FIGURE_RECOVERY_ENABLED:
            upload_json_artifact(doc_id, run_id, "figures.json", [])
            upload_json_artifact(doc_id, run_id, "step4a-result.json", {
                "page_count": page_count,
                "figures_total": 0,
                "qualified": 0,
                "rejected": 0,
                "recovered": 0,
            })
            logger.info("[step4a] doc_id=%s no figures", doc_id)
            return {"figures_total": 0, "qualified": 0}

        pdf_bytes = download_document(blob_name)
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")

        document_title = _document_title(adi_raw, blob_name)
        section_headings = _section_headings(adi_raw)

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
        adi_bboxes_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
        max_adi_figure_index = -1

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

                    adi_bboxes_by_page.setdefault(pnum, []).append(bbox)
                    max_adi_figure_index = max(max_adi_figure_index, fig.figure_index)

                    _, y0, _, _ = bbox
                    features = _candidate_features(bbox, page_w, page_h, furniture)

                    has_ref = _has_reference(fig.caption, page_text, bbox)
                    nearby_text = _nearby_text_context(page_text, bbox)
                    section_heading = _section_heading_for(section_headings, pnum, y0)

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
                        document_title=document_title,
                        section_heading=section_heading,
                        nearby_text=nearby_text,
                        provenance="reader",
                    )
                    candidates.append(candidate)
                    pending_qualification.append((candidate, features, bbox, has_ref))
                    pages_by_position_group.setdefault(
                        features.normalized_position_group, set()
                    ).add(pnum)

            # Recovery cross-check (add-missed-figure-detection): placements
            # the PDF itself declares that ADI never reported a figure for.
            # Recovered candidates re-enter the same pending_qualification
            # list below, so they go through identical 4B rules and cropping.
            recovered_count = 0
            if FIGURE_RECOVERY_ENABLED:
                pages_classification, placements_by_page = _load_recovery_inputs(
                    doc_id, run_id
                )
                if pages_classification and placements_by_page:
                    next_recovered_index = _first_recovered_index(max_adi_figure_index)
                    for page_result in adi_results:
                        pnum = page_result.page_number
                        page_class = pages_classification.get(pnum)
                        if not page_class or not page_class.cross_check_eligible:
                            continue
                        placements = placements_by_page.get(pnum, [])
                        if not placements:
                            continue
                        page_w, page_h = _page_dimensions(adi_raw, pnum)
                        if page_w <= 0 or page_h <= 0:
                            continue
                        furniture = _furniture_regions(adi_raw, pnum)
                        page_text = _nearby_text(adi_raw, pnum)
                        adi_bboxes = adi_bboxes_by_page.get(pnum, [])

                        for placement in placements:
                            bbox = _placement_rect_to_inches(placement.rect)
                            if not bbox:
                                continue
                            if _already_detected(
                                bbox, adi_bboxes, FIGURE_RECOVERY_OVERLAP_THRESHOLD
                            ):
                                continue

                            features = _candidate_features(bbox, page_w, page_h, furniture)
                            has_ref = _recovered_candidate_has_reference()
                            nearby_text = _nearby_text_context(page_text, bbox)
                            section_heading = _section_heading_for(
                                section_headings, pnum, bbox[1]
                            )

                            figure_index = next_recovered_index
                            next_recovered_index += 1

                            candidate = FigureCandidate(
                                document_id=doc_id,
                                source_file=blob_name,
                                page=pnum,
                                figure_index=figure_index,
                                figure_id=f"recovered-p{pnum}-{figure_index}",
                                bounding_polygon=_bbox_to_polygon(bbox),
                                caption=None,
                                page_width=page_w,
                                page_height=page_h,
                                features=features,
                                document_title=document_title,
                                section_heading=section_heading,
                                nearby_text=nearby_text,
                                provenance="recovered",
                            )
                            candidates.append(candidate)
                            pending_qualification.append(
                                (candidate, features, bbox, has_ref)
                            )
                            pages_by_position_group.setdefault(
                                features.normalized_position_group, set()
                            ).add(pnum)
                            adi_bboxes.append(bbox)  # avoid re-recovering the same spot twice
                            recovered_count += 1

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
        recovered_qualified = sum(1 for c in qualified if c.provenance == "recovered")

        upload_json_artifact(
            doc_id, run_id, "figures.json", [c.model_dump() for c in candidates]
        )
        upload_json_artifact(doc_id, run_id, "step4a-result.json", {
            "page_count": page_count,
            "figures_total": len(candidates),
            "qualified": len(qualified),
            "rejected": len(candidates) - len(qualified),
            "rejected_by_reason": rejected_by_reason,
            "recovered": recovered_count,
            "recovered_qualified": recovered_qualified,
        })

        track_metric("figures_total", len(candidates), doc_id=doc_id)
        track_metric("figures_qualified", len(qualified), doc_id=doc_id)
        track_metric("figures_recovered", recovered_count, doc_id=doc_id)

        logger.info(
            "[step4a] doc_id=%s figures=%d qualified=%d recovered=%d rejected=%s",
            doc_id, len(candidates), len(qualified), recovered_count,
            rejected_by_reason or "{}",
        )
        return {"figures_total": len(candidates), "qualified": len(qualified)}
