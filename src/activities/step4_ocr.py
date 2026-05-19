"""
Step 4 — OCR via Mistral (Azure AI Foundry).

Two separate Durable activity functions, both registered in function_app.py:

  extract_page(ctx, page) → sas_url
    Downloads the full PDF, extracts page N as a single-page PDF using PyMuPDF,
    uploads it to processing/{doc_id}/{run_id}/pages/page-{N}.pdf,
    returns a 1-hour SAS URL.

  ocr_page(ctx, page, sas_url) → dict
    Calls Mistral OCR API with the SAS URL (no base64 encoding).
    Writes ocr-page-{N}.md and any p{N}-img-{M}.jpeg images to Blob Storage.

Auth:
  Mistral OCR (Foundry Classic) does not support Managed Identity.
  The endpoint key is retrieved from Key Vault via DefaultAzureCredential.
  See GitHub issue: "Entra auth: replace Foundry key with MI once supported"

Ported from v1 step4-mistral.ts.
"""

from __future__ import annotations

import io
import logging
import os
import time

import fitz  # PyMuPDF
import httpx

from shared.auth import get_foundry_key
from shared.blob_client import (
    download_document,
    generate_page_sas_url,
    upload_artifact,
    upload_json_artifact,
)
from shared.telemetry import timed_step, track_metric

logger = logging.getLogger(__name__)

FOUNDRY_ENDPOINT = os.environ.get("FOUNDRY_ENDPOINT", "").rstrip("/")
FOUNDRY_OCR_DEPLOYMENT = os.environ.get("FOUNDRY_OCR_DEPLOYMENT", "mistral-ocr")
CALL_DELAY_S = 1.0
MAX_RETRIES = 4


# ── extract_page ──────────────────────────────────────────────────────────


def extract_page_main(ctx: dict) -> str:
    """
    Extract a single page from the source PDF and upload it to Blob Storage.
    Returns the SAS URL for the page PDF.
    """
    doc_id: str = ctx["doc_id"]
    run_id: str = ctx["run_id"]
    blob_name: str = ctx["blob_name"]
    page: int = ctx["page"]  # 1-based

    with timed_step("extract_page", doc_id, run_id, page=page):
        pdf_bytes = download_document(blob_name)
        src_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        new_doc = fitz.open()
        new_doc.insert_pdf(src_doc, from_page=page - 1, to_page=page - 1)
        page_bytes = new_doc.tobytes()
        new_doc.close()
        src_doc.close()

        upload_artifact(doc_id, run_id, f"pages/page-{page}.pdf", page_bytes)
        sas_url = generate_page_sas_url(doc_id, run_id, page)

        logger.info(
            "[extract_page] doc_id=%s page=%d size=%dKB",
            doc_id, page, len(page_bytes) // 1024,
        )
        return sas_url


# ── ocr_page ──────────────────────────────────────────────────────────────


def _ocr_with_retry(url: str, key: str, body: dict) -> dict:
    delay = 3.0
    for attempt in range(MAX_RETRIES + 1):
        resp = httpx.post(
            url,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            json=body,
            timeout=120.0,
        )
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp.json()
        if attempt < MAX_RETRIES:
            logger.warning("[ocr_page] rate limited, retrying in %.0fs", delay)
            time.sleep(delay)
            delay *= 2
    resp.raise_for_status()
    return resp.json()


def ocr_page_main(ctx: dict) -> dict:
    """
    Run Mistral OCR on a single page PDF using its SAS URL.
    Writes ocr-page-{N}.md and any extracted images to Blob Storage.
    """
    doc_id: str = ctx["doc_id"]
    run_id: str = ctx["run_id"]
    page: int = ctx["page"]
    sas_url: str = ctx["sas_url"]

    with timed_step("ocr_page", doc_id, run_id, page=page):
        ocr_url = f"{FOUNDRY_ENDPOINT}/providers/mistral/azure/ocr"
        key = get_foundry_key()

        body = {
            "model": FOUNDRY_OCR_DEPLOYMENT,
            "document": {"type": "document_url", "document_url": sas_url},
            "include_image_base64": True,
        }

        t0 = time.monotonic()
        result = _ocr_with_retry(ocr_url, key, body)
        duration_ms = (time.monotonic() - t0) * 1000

        page_data = (result.get("pages") or [{}])[0]
        markdown: str = page_data.get("markdown", "")

        # Prefix image IDs with page number to avoid cross-page filename collisions
        images_raw = page_data.get("images") or []
        image_blobs: list[str] = []
        for i, img in enumerate(images_raw):
            img_id = f"p{page}-img-{i}.jpeg"
            b64 = img.get("image_base64", "")
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            if b64:
                import base64
                img_bytes = base64.b64decode(b64)
                upload_artifact(doc_id, run_id, img_id, img_bytes)
                image_blobs.append(img_id)
            # Rewrite image IDs in markdown
            old_id = img.get("id", "")
            if old_id:
                markdown = markdown.replace(old_id, img_id)

        upload_artifact(doc_id, run_id, f"ocr-page-{page}.md", markdown)

        time.sleep(CALL_DELAY_S)

        track_metric("ocr_chars", len(markdown), doc_id=doc_id, page=page)
        logger.info(
            "[ocr_page] doc_id=%s page=%d chars=%d images=%d %.0fms",
            doc_id, page, len(markdown), len(image_blobs), duration_ms,
        )
        return {
            "page": page,
            "markdown_length": len(markdown),
            "image_count": len(image_blobs),
        }
