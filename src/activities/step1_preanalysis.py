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

import fitz  # PyMuPDF

from shared.blob_client import download_document, upload_json_artifact
from shared.telemetry import timed_step
from models.types import PreAnalysisResult

logger = logging.getLogger(__name__)


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
        total_chars = sum(len(doc[i].get_text()) for i in range(page_count))
        avg_chars = total_chars / max(page_count, 1)
        has_text = avg_chars > 50
        doc.close()

        result = PreAnalysisResult(
            blob_name=blob_name,
            doc_id=doc_id,
            page_count=page_count,
            has_text=has_text,
            file_size_bytes=file_size_bytes,
        )

        upload_json_artifact(doc_id, run_id, "step1-result.json", result.model_dump())

        logger.info(
            "[step1] doc_id=%s pages=%d has_text=%s size=%.1fKB avg_chars/page=%.0f",
            doc_id, page_count, has_text, file_size_bytes / 1024, avg_chars,
        )
        return result.model_dump()
