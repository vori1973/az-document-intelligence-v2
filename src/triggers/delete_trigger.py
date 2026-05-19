"""
delete_trigger — EventGrid BlobDeleted trigger.

Receives a BlobDeleted event when a PDF is removed from documents/.
Resolves the doc_id from the stored mapping and deletes:
  1. All AI Search chunks for the document
  2. All processing artifacts in Blob Storage
"""

from __future__ import annotations

import logging
import os

import azure.functions as func
from azure.search.documents import SearchClient

from shared.auth import get_credential
from shared.blob_client import delete_doc_artifacts, resolve_doc_id
from shared.telemetry import log_step_start, log_step_end, log_step_error, track_metric

logger = logging.getLogger(__name__)

SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX", "document-chunks")


def _delete_search_chunks(doc_id: str) -> int:
    client = SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=SEARCH_INDEX,
        credential=get_credential(),
    )
    results = client.search(
        search_text="*",
        filter=f"document_id eq '{doc_id}'",
        select=["id"],
        top=1000,
    )
    docs = [{"@search.action": "delete", "id": r["id"]} for r in results]
    if not docs:
        return 0
    client.upload_documents(docs)
    return len(docs)


async def delete_trigger_main(event: func.EventGridEvent) -> None:
    data = event.get_json()
    blob_name: str = data.get("url", "").split("/documents/", 1)[-1]

    if not blob_name.lower().endswith(".pdf"):
        return

    logger.info("[delete_trigger] BlobDeleted: %s", blob_name)

    doc_id = resolve_doc_id(blob_name)
    if not doc_id:
        logger.warning("[delete_trigger] No doc_id mapping found for %s — skipping", blob_name)
        return

    run_id = "delete"
    log_step_start("delete_trigger", doc_id, run_id, blob_name=blob_name)
    try:
        chunk_count = _delete_search_chunks(doc_id)
        blob_count = delete_doc_artifacts(doc_id)
        track_metric("chunks_deleted", chunk_count, doc_id=doc_id)
        track_metric("artifacts_deleted", blob_count, doc_id=doc_id)
        log_step_end("delete_trigger", doc_id, run_id, duration_ms=0,
                     chunks_deleted=chunk_count, blobs_deleted=blob_count)
        logger.info(
            "[delete_trigger] Cleaned up doc_id=%s: %d chunks, %d blobs",
            doc_id, chunk_count, blob_count,
        )
    except Exception as exc:
        log_step_error("delete_trigger", doc_id, run_id, exc)
        raise
