"""
Step 5 — Build RAG chunks.

Reads adi-raw.json, adi-results.json, routing.json, and ocr-page-{N}.md from Blob Storage.
Produces three chunk types:
  - table_row : one chunk per data row, fused with column headers and lead-in prose
  - paragraph : sliding window (~500 tokens, ~100 overlap) over ADI paragraph content
  - figure    : one chunk per figure (caption + image blob path)

Writes chunks.json, tables-debug.md, tables-flags.md, tables-stats.md.

Ported from v1 step5-index.ts — all logic preserved.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Optional

from shared.blob_client import download_artifact, download_json_artifact, upload_artifact, upload_json_artifact
from shared.telemetry import timed_step, track_metric
from models.types import AdiPageResult, RagChunk, RagCitation, RoutingDecision

logger = logging.getLogger(__name__)

ADI_SOURCE = f"ADI-{os.environ.get('ADI_MODEL', 'prebuilt-layout')}"
OCR_SOURCE = os.environ.get("FOUNDRY_OCR_DEPLOYMENT", "ocr")
TABLE_CONFIDENCE_THRESHOLD = 0.75
IMAGE_ARTIFACT_MIN_CONFIDENCE = 0.2
CHUNK_TOKENS = int(os.environ.get("CHUNK_TOKENS", "500"))
CHUNK_OVERLAP_TOKENS = int(os.environ.get("CHUNK_OVERLAP_TOKENS", "100"))
MIN_LEAD_IN_CHARS = int(os.environ.get("CHUNK_LEAD_IN_MIN_CHARS", "30"))
MISTRAL_FRAGMENTATION_THRESHOLD = 0.6

PARA_NOISE_ROLES = {"pageNumber", "pageHeader", "pageFooter"}


# ── Token counting ────────────────────────────────────────────────────────


def _token_count(text: str) -> int:
    return len(text.split()) if text.strip() else 0


# ── Polygon union ─────────────────────────────────────────────────────────


def _union_polygon(polygons: list[list[float]]) -> list[float]:
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for poly in polygons:
        for i in range(0, len(poly), 2):
            min_x = min(min_x, poly[i])
            max_x = max(max_x, poly[i])
        for i in range(1, len(poly), 2):
            min_y = min(min_y, poly[i])
            max_y = max(max_y, poly[i])
    if min_x == float("inf"):
        return []
    return [min_x, min_y, max_x, min_y, max_x, max_y, min_x, max_y]


# ── Mistral pipe-table parser ─────────────────────────────────────────────


def _parse_mistral_tables(markdown: str) -> list[dict]:
    """Parse pipe-tables from Mistral OCR markdown. Returns list of {headers, data}."""
    # Pre-process: join continuation lines into their parent pipe-row
    raw_lines = markdown.split("\n")
    lines: list[str] = []
    for raw in raw_lines:
        t = raw.strip()
        if lines:
            prev = lines[-1].strip()
            if prev.startswith("|") and not prev.endswith("|") and not t.startswith("|"):
                lines[-1] = lines[-1].rstrip() + " " + t
                continue
        lines.append(raw)

    tables: list[dict] = []
    in_table = False
    past_sep = False
    header_rows: list[list[str]] = []
    data_rows: list[list[str]] = []

    def flush():
        nonlocal in_table, past_sep, header_rows, data_rows
        if header_rows or data_rows:
            tables.append({"headers": header_rows, "data": data_rows})
        header_rows, data_rows, in_table, past_sep = [], [], False, False

    for line in lines:
        trimmed = line.strip()
        if trimmed.startswith("|") and trimmed.endswith("|") and len(trimmed) > 1:
            in_table = True
            if re.match(r"^\|[\s\-|:]+\|$", trimmed):
                past_sep = True
                continue
            cells = [c.strip() for c in trimmed.split("|")[1:-1]]
            if past_sep:
                data_rows.append(cells)
            else:
                header_rows.append(cells)
        elif in_table:
            flush()
    if in_table:
        flush()
    return tables


# ── ADI cell grid ─────────────────────────────────────────────────────────


def _build_adi_cell_grid(data_cells: list, row_count: int, col_count: int) -> tuple[list, list]:
    values = [[""] * col_count for _ in range(row_count)]
    row_spanned = [[False] * col_count for _ in range(row_count)]

    for cell in data_cells:
        raw = (cell.get("content") or "").strip()
        if raw == ":selected:":
            text = "checked"
        elif raw == ":unselected:":
            text = "unchecked"
        else:
            text = re.sub(r":(?:un)?selected:", "", raw).strip()
            text = re.sub(r"\s+", " ", text)

        row_span = cell.get("row_span") or 1
        col_span = cell.get("column_span") or 1
        for r in range(cell.get("row_index", 0), min(cell.get("row_index", 0) + row_span, row_count)):
            for c in range(cell.get("column_index", 0), min(cell.get("column_index", 0) + col_span, col_count)):
                if text:
                    values[r][c] = text
                if row_span > 1 and r > cell.get("row_index", 0):
                    row_spanned[r][c] = True
    return values, row_spanned


def _normalize_adi_grid(values: list, row_count: int, col_count: int) -> list:
    if row_count == 0 or col_count <= 1:
        return values
    result = [row[:] for row in values]
    g_start = 0
    while g_start < row_count:
        label = result[g_start][0]
        g_end = g_start + 1
        while g_end < row_count and result[g_end][0] == label:
            g_end += 1
        if g_end - g_start > 1 and label:
            for col in range(1, col_count):
                non_empty = [r for r in range(g_start, g_end) if result[r][col].strip()]
                if len(non_empty) == 1:
                    val = result[non_empty[0]][col]
                    for r in range(g_start, g_end):
                        result[r][col] = val
        g_start = g_end
    return result


def _normalize_mistral_table(rows: list, adi_values: list, adi_row_spanned: list, row_indices: list) -> list:
    if not rows:
        return rows
    col_count = max((len(r) for r in rows), default=0)

    # Pass 1: fill-right (column span detection)
    after_fill_right = []
    for ri, row in enumerate(rows):
        row_idx = row_indices[ri]
        result = [(row[c] if c < len(row) else "").strip() for c in range(col_count)]
        for col in range(1, col_count):
            if not result[col] and result[col - 1]:
                adi_val = ((adi_values[row_idx][col] if row_idx < len(adi_values) and col < len(adi_values[row_idx]) else "") or "").strip()
                if adi_val and adi_val != result[col - 1] and adi_val in result[col - 1]:
                    result[col] = result[col - 1]
        after_fill_right.append(result)

    # Pass 2: fill-down with ADI rowspan override
    last_seen = [""] * col_count
    normalized = []
    for ri, row in enumerate(after_fill_right):
        row_idx = row_indices[ri]
        next_row_idx = row_indices[ri + 1] if ri + 1 < len(row_indices) else -1
        new_row = []
        for col, val in enumerate(row):
            is_spanned = (adi_row_spanned[row_idx][col] if row_idx < len(adi_row_spanned) and col < len(adi_row_spanned[row_idx]) else False)
            span_continues = (next_row_idx >= 0 and next_row_idx < len(adi_row_spanned) and col < len(adi_row_spanned[next_row_idx]) and adi_row_spanned[next_row_idx][col])
            if is_spanned or span_continues:
                adi_val = ((adi_values[row_idx][col] if row_idx < len(adi_values) and col < len(adi_values[row_idx]) else "") or "").strip()
                if adi_val:
                    last_seen[col] = adi_val
                    new_row.append(adi_val)
                    continue
            if val:
                last_seen[col] = val
                new_row.append(val)
            else:
                new_row.append(last_seen[col])
        normalized.append(new_row)
    return normalized


# ── Lead-in prose ─────────────────────────────────────────────────────────


def _last_sentences(content: str, n: int) -> str:
    text = content.strip()
    if len(text) < MIN_LEAD_IN_CHARS:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[-n:]).strip()


def _find_table_lead_in(table: dict, paragraphs: list, page_num: int) -> str:
    table_start = (table.get("spans") or [{}])[0].get("offset", float("inf"))
    candidates = []
    for p in paragraphs:
        if (p.get("role") or "") in PARA_NOISE_ROLES:
            continue
        if not any(r.get("page_number") == page_num for r in (p.get("bounding_regions") or [])):
            continue
        spans = p.get("spans") or []
        if not spans:
            continue
        p_end = spans[-1].get("offset", 0) + spans[-1].get("length", 0)
        if p_end < table_start:
            candidates.append((p_end, p))
    candidates.sort(key=lambda x: -x[0])
    for _, p in candidates:
        result = _last_sentences(p.get("content") or "", 2)
        if result:
            return result
    return ""


# ── Table row chunks ──────────────────────────────────────────────────────


def _build_table_row_chunks(
    adi_raw: dict,
    doc_id: str,
    blob_name: str,
    mistral_markdown: dict[int, str],
    adi_page_results: list[AdiPageResult],
) -> tuple[list[RagChunk], dict[int, str]]:
    chunks: list[RagChunk] = []
    table_labels: dict[int, str] = {}
    tables = adi_raw.get("tables") or []

    tables_by_page: dict[int, list[int]] = {}
    for gi, t in enumerate(tables):
        pnum = ((t.get("bounding_regions") or [{}])[0].get("page_number") or 1)
        tables_by_page.setdefault(pnum, []).append(gi)

    flags: list[dict] = []
    stats: list[dict] = []

    for page_num, global_indices in tables_by_page.items():
        mistral_md = mistral_markdown.get(page_num)
        mistral_tables = _parse_mistral_tables(mistral_md) if mistral_md else []

        for local_idx, gi in enumerate(global_indices):
            table = tables[gi]
            col_count = table.get("column_count", 0)

            # Build column headers
            col_headers = [""] * col_count
            header_cells = [c for c in (table.get("cells") or []) if c.get("kind") == "columnHeader"]
            header_cells.sort(key=lambda c: (c.get("row_index", 0), c.get("column_index", 0)))
            for cell in header_cells:
                span = cell.get("column_span") or 1
                text = re.sub(r"\s+", " ", (cell.get("content") or "").strip())
                if not text:
                    continue
                for col in range(cell.get("column_index", 0), min(cell.get("column_index", 0) + span, col_count)):
                    col_headers[col] = f"{col_headers[col]} / {text}" if col_headers[col] else text

            caption = ((table.get("caption") or {}).get("content") or "").strip()

            # Derive canonical table label
            label = caption
            if not label:
                non_empty = [h for h in col_headers if h]
                label = " | ".join(non_empty) if non_empty else ""
            if not label:
                row0 = sorted(
                    [c for c in (table.get("cells") or []) if c.get("row_index") == 0],
                    key=lambda c: c.get("column_index", 0),
                )
                label = " | ".join((c.get("content") or "").strip() for c in row0 if (c.get("content") or "").strip())
            table_labels[gi] = label

            table_lead_in = _find_table_lead_in(table, adi_raw.get("paragraphs") or [], page_num)

            data_cells = [c for c in (table.get("cells") or []) if c.get("kind") != "columnHeader"]
            row_map: dict[int, list] = {}
            for cell in data_cells:
                ri = cell.get("row_index", 0)
                row_map.setdefault(ri, []).append(cell)
            row_indices = sorted(row_map.keys())

            max_row = max(row_indices) + 1 if row_indices else 0
            adi_values, adi_row_spanned = _build_adi_cell_grid(data_cells, max_row, col_count)
            norm_adi_values = _normalize_adi_grid(adi_values, max_row, col_count)

            # Complexity signals from step2
            adi_page_result = next((r for r in adi_page_results if r.page_number == page_num), None)
            adi_table_conf = adi_page_result.tables[local_idx] if (adi_page_result and local_idx < len(adi_page_result.tables)) else None
            complexity_reasons = adi_table_conf.complexity_reasons if adi_table_conf else []
            has_rotated = any("rotated" in r for r in complexity_reasons)
            has_content_complexity = any("paragraph-length" in r or "column width" in r for r in complexity_reasons)
            max_header_row = max((c.get("row_index", 0) for c in header_cells), default=0)
            has_multi_level_headers = max_header_row >= 2

            raw_mistral = mistral_tables[local_idx] if local_idx < len(mistral_tables) else None

            # Image artifact check: ADI table with no Mistral tables and very low confidence → skip
            if (
                mistral_md
                and not mistral_tables
                and adi_table_conf
                and adi_table_conf.min_cell_confidence < IMAGE_ARTIFACT_MIN_CONFIDENCE
            ):
                stats.append({"page": page_num, "table_index": local_idx, "source": "adi", "flag_types": ["image_artifact"]})
                flags.append({"page": page_num, "table_index": local_idx, "caption": caption, "source": "adi",
                               "flags": [{"type": "image_artifact", "detail": f"min_conf={adi_table_conf.min_cell_confidence:.3f}, no Mistral tables on page"}]})
                continue

            # Decide source: Mistral or ADI
            use_mistral = bool(raw_mistral and mistral_md)
            flag_types: list[str] = []

            if use_mistral:
                mistral_data_rows = raw_mistral["data"] if raw_mistral else []
                mistral_row_count = len(mistral_data_rows)
                adi_row_count = len(row_indices)
                row_ratio = mistral_row_count / adi_row_count if adi_row_count > 0 else 1.0

                if has_rotated or (has_multi_level_headers and not has_rotated) or row_ratio < MISTRAL_FRAGMENTATION_THRESHOLD:
                    use_mistral = False
                    if row_ratio < MISTRAL_FRAGMENTATION_THRESHOLD:
                        flag_types.append("row_count_mismatch")
                    if has_multi_level_headers:
                        flag_types.append("mistral_multi_header")

            if use_mistral and raw_mistral:
                norm_mistral_data = _normalize_mistral_table(
                    raw_mistral["data"], adi_values, adi_row_spanned, row_indices
                )
                col_headers_for_text = raw_mistral["headers"][-1] if raw_mistral["headers"] else col_headers
                source = OCR_SOURCE
                data_to_use = norm_mistral_data
            else:
                col_headers_for_text = col_headers
                source = ADI_SOURCE
                data_to_use = [norm_adi_values[ri] for ri in row_indices]

            # Emit one chunk per data row
            for row_i, row_cells in enumerate(data_to_use):
                actual_row_idx = row_indices[row_i] if row_i < len(row_indices) else row_i
                parts: list[str] = []
                if table_lead_in:
                    parts.append(f"[Context: {table_lead_in}]")
                if label:
                    parts.append(f"[Table: {label}]")
                for col, val in enumerate(row_cells):
                    header = col_headers_for_text[col] if col < len(col_headers_for_text) else ""
                    header = header if isinstance(header, str) else ""
                    cell_text = f"{header}: {val}" if header and val else (header or val or "")
                    if cell_text:
                        parts.append(cell_text)
                text = " | ".join(parts)
                if not text.strip():
                    continue

                # Bounding polygon: union of all cells in this row
                row_cells_raw = row_map.get(actual_row_idx, [])
                polygons = [
                    (c.get("bounding_regions") or [{}])[0].get("polygon") or []
                    for c in row_cells_raw
                ]
                polygon = _union_polygon([p for p in polygons if p])

                chunk_id = hashlib.sha256(
                    f"{doc_id}-table-{gi}-row-{actual_row_idx}".encode()
                ).hexdigest()[:32]

                chunks.append(RagChunk(
                    chunk_id=chunk_id,
                    type="table_row",
                    source=source,
                    source_file=blob_name,
                    text_for_embedding=text,
                    citation=RagCitation(
                        document_id=doc_id,
                        page=page_num,
                        bounding_polygon=polygon,
                        table_index=gi,
                        row_index=actual_row_idx,
                    ),
                ))

            empty_ratio = sum(1 for row in data_to_use for v in row if not v.strip()) / max(sum(len(r) for r in data_to_use), 1)
            if empty_ratio > 0.5:
                flag_types.append("high_empty_ratio")

            stats.append({"page": page_num, "table_index": local_idx,
                          "source": "mistral" if use_mistral else "adi", "flag_types": flag_types})
            if flag_types:
                flags.append({"page": page_num, "table_index": local_idx, "caption": caption,
                               "source": "mistral" if use_mistral else "adi",
                               "flags": [{"type": t, "detail": ""} for t in flag_types]})

    return chunks, table_labels, flags, stats


# ── Paragraph chunks ──────────────────────────────────────────────────────


def _build_paragraph_chunks(
    adi_raw: dict,
    doc_id: str,
    blob_name: str,
    table_labels: dict[int, str],
) -> list[RagChunk]:
    chunks: list[RagChunk] = []
    paragraphs = adi_raw.get("paragraphs") or []
    tables = adi_raw.get("tables") or []

    # Build table span ranges for inline pointer injection
    table_spans: list[tuple[int, int, int]] = []  # (start, end, global_idx)
    for gi, t in enumerate(tables):
        for span in (t.get("spans") or []):
            table_spans.append((span.get("offset", 0), span.get("offset", 0) + span.get("length", 0), gi))

    window: list[dict] = []
    window_tokens = 0

    def flush_window(page_num: int, polygon: list[float], window_items: list[dict]) -> Optional[RagChunk]:
        text = " ".join(item["text"] for item in window_items if item["text"].strip())
        if not text.strip():
            return None
        chunk_id = hashlib.sha256(
            f"{doc_id}-para-{page_num}-{(window_items[0].get('offset') or 0)}".encode()
        ).hexdigest()[:32]
        return RagChunk(
            chunk_id=chunk_id,
            type="paragraph",
            source=ADI_SOURCE,
            source_file=blob_name,
            text_for_embedding=text,
            citation=RagCitation(
                document_id=doc_id,
                page=page_num,
                bounding_polygon=polygon,
            ),
        )

    current_page = None
    page_window: list[dict] = []
    page_polygons: list[list[float]] = []

    for para in paragraphs:
        role = para.get("role") or ""
        if role in PARA_NOISE_ROLES:
            continue
        content = (para.get("content") or "").strip()
        if not content:
            continue

        pnum = ((para.get("bounding_regions") or [{}])[0].get("page_number") or 1)
        polygon = (para.get("bounding_regions") or [{}])[0].get("polygon") or []

        # Inject table pointer if this paragraph precedes a table
        span_offset = (para.get("spans") or [{}])[0].get("offset", 0)
        for t_start, t_end, gi in table_spans:
            if abs(t_start - span_offset) < 200 and gi in table_labels:
                content = f"{content} [Table: {table_labels[gi]}]"
                break

        tokens = _token_count(content)
        if current_page is None:
            current_page = pnum

        if pnum != current_page:
            # Flush page window
            if page_window:
                chunk = flush_window(
                    current_page,
                    _union_polygon(page_polygons),
                    page_window,
                )
                if chunk:
                    chunks.append(chunk)
            page_window = []
            page_polygons = []
            current_page = pnum

        # Sliding window: emit chunk when budget exceeded
        page_window.append({"text": content, "offset": span_offset, "tokens": tokens})
        page_polygons.append(polygon)
        window_tokens_total = sum(item["tokens"] for item in page_window)

        if window_tokens_total >= CHUNK_TOKENS:
            chunk = flush_window(pnum, _union_polygon(page_polygons), page_window)
            if chunk:
                chunks.append(chunk)
            # Overlap: keep last CHUNK_OVERLAP_TOKENS worth of items
            overlap_items: list[dict] = []
            overlap_t = 0
            for item in reversed(page_window):
                if overlap_t + item["tokens"] > CHUNK_OVERLAP_TOKENS:
                    break
                overlap_items.insert(0, item)
                overlap_t += item["tokens"]
            page_window = overlap_items
            page_polygons = [polygon]

    if page_window:
        chunk = flush_window(current_page or 1, _union_polygon(page_polygons), page_window)
        if chunk:
            chunks.append(chunk)

    return chunks


# ── Figure chunks ─────────────────────────────────────────────────────────


def _build_figure_chunks(
    adi_page_results: list[AdiPageResult],
    doc_id: str,
    blob_name: str,
    run_id: str,
) -> list[RagChunk]:
    chunks: list[RagChunk] = []
    for page_result in adi_page_results:
        for fig in page_result.figures:
            text = f"[Figure] {fig.caption or ''} (Page {fig.page_number})".strip()
            chunk_id = hashlib.sha256(
                f"{doc_id}-fig-{fig.figure_index}-p{fig.page_number}".encode()
            ).hexdigest()[:32]

            # Use ADI-fetched image if available, otherwise OCR image
            image_blob = fig.adi_image_blob
            if not image_blob:
                image_blob = f"p{fig.page_number}-adi-fig-0.jpeg"

            chunks.append(RagChunk(
                chunk_id=chunk_id,
                type="figure",
                source=ADI_SOURCE,
                source_file=blob_name,
                text_for_embedding=text,
                image_blob=image_blob,
                citation=RagCitation(
                    document_id=doc_id,
                    page=fig.page_number,
                    bounding_polygon=fig.polygon,
                    figure_index=fig.figure_index,
                ),
            ))
    return chunks


# ── Main ──────────────────────────────────────────────────────────────────


def step5_chunks_main(ctx: dict) -> dict:
    doc_id: str = ctx["doc_id"]
    run_id: str = ctx["run_id"]
    blob_name: str = ctx["blob_name"]

    with timed_step("step5_chunks", doc_id, run_id):
        adi_raw = download_json_artifact(doc_id, run_id, "adi-raw.json")
        adi_results_raw = download_json_artifact(doc_id, run_id, "adi-results.json")
        routing_raw = download_json_artifact(doc_id, run_id, "routing.json")

        adi_page_results = [AdiPageResult.model_validate(r) for r in adi_results_raw]
        routing = RoutingDecision.model_validate(routing_raw)

        # Load OCR markdown per page
        mistral_markdown: dict[int, str] = {}
        for page in routing.pages_for_ocr:
            try:
                md_bytes = download_artifact(doc_id, run_id, f"ocr-page-{page}.md")
                mistral_markdown[page] = md_bytes.decode("utf-8")
            except Exception:
                logger.warning("[step5] No OCR markdown for page %d", page)

        table_chunks, table_labels, flags, stats = _build_table_row_chunks(
            adi_raw, doc_id, blob_name, mistral_markdown, adi_page_results
        )
        para_chunks = _build_paragraph_chunks(adi_raw, doc_id, blob_name, table_labels)
        figure_chunks = _build_figure_chunks(adi_page_results, doc_id, blob_name, run_id)

        all_chunks = table_chunks + para_chunks + figure_chunks

        upload_json_artifact(doc_id, run_id, "chunks.json", [c.model_dump() for c in all_chunks])

        # Debug artifacts
        _write_tables_debug(flags, doc_id, run_id)
        _write_tables_stats(stats, doc_id, run_id)

        track_metric("chunks_table_rows", len(table_chunks), doc_id=doc_id)
        track_metric("chunks_paragraphs", len(para_chunks), doc_id=doc_id)
        track_metric("chunks_figures", len(figure_chunks), doc_id=doc_id)

        logger.info(
            "[step5] doc_id=%s table_rows=%d paragraphs=%d figures=%d total=%d",
            doc_id, len(table_chunks), len(para_chunks), len(figure_chunks), len(all_chunks),
        )
        upload_json_artifact(doc_id, run_id, "step5-result.json", {
            "paragraphs": len(para_chunks),
            "table_rows": len(table_chunks),
            "figures": len(figure_chunks),
            "total": len(all_chunks),
        })
        return {"total_chunks": len(all_chunks)}


def _write_tables_debug(flags: list[dict], doc_id: str, run_id: str) -> None:
    if not flags:
        upload_artifact(doc_id, run_id, "tables-flags.md", "# Tables Flags\n\nNo flagged tables.\n")
        return
    lines = ["# Tables Flags\n", f"{len(flags)} table(s) flagged for review.\n"]
    for f in flags:
        lines.append(f"## Page {f['page']} · Table {f['table_index']} · source: {f['source']}")
        label = f'"{f["caption"]}"' if f.get("caption") else f"Table {f['table_index']}"
        lines.append(f"**{label}**\n")
        for fl in (f.get("flags") or []):
            lines.append(f"- `{fl['type']}` — {fl.get('detail', '')}")
        lines.append("")
    upload_artifact(doc_id, run_id, "tables-flags.md", "\n".join(lines))


def _write_tables_stats(stats: list[dict], doc_id: str, run_id: str) -> None:
    total = len(stats)
    ocr_count = sum(1 for s in stats if s.get("source") == "mistral")
    adi_count = total - ocr_count
    pct = lambda n: f"{round(n / total * 100)}%" if total else "0%"

    lines = ["# Tables Statistics\n", "## Summary\n"]
    lines += [
        "| | Count | % |", "|---|---:|---:|",
        f"| Total tables | {total} | 100% |",
        f"| Using OCR ({OCR_SOURCE}) | {ocr_count} | {pct(ocr_count)} |",
        f"| Fell back to ADI | {adi_count} | {pct(adi_count)} |", "",
    ]
    upload_artifact(doc_id, run_id, "tables-stats.md", "\n".join(lines))
