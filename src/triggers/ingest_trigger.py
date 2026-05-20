"""
ingest_trigger — EventGrid BlobCreated trigger.

Receives a BlobCreated event from Azure Event Grid when a PDF is uploaded
to the documents/ container. Starts (or re-starts) the Durable orchestrator.

Idempotency:
  - Computes SHA-256 of PDF content → doc_id
  - If the same doc_id is already in progress or succeeded → skip
  - If a previous doc_id exists for this blob_name → run stale-chunk cleanup first
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid

import azure.durable_functions as df
import azure.functions as func

from shared.blob_client import download_document, resolve_doc_id, store_doc_id_mapping
from shared.telemetry import log_step_start
from models.types import PipelineContext

logger = logging.getLogger(__name__)


async def ingest_trigger_main(event: func.EventGridEvent, starter: df.DurableOrchestrationClient) -> None:
    data = event.get_json()
    blob_url: str = data.get("url", "")
    blob_name: str = data.get("url", "").split("/documents/", 1)[-1]

    if not blob_name.lower().endswith(".pdf"):
        logger.info("Skipping non-PDF blob: %s", blob_name)
        return

    logger.info("[ingest_trigger] BlobCreated: %s", blob_name)

    # Download PDF and compute content hash → doc_id
    pdf_bytes = download_document(blob_name)
    doc_id = hashlib.sha256(pdf_bytes).hexdigest()[:16]

    # Check for existing mapping (update scenario)
    old_doc_id = resolve_doc_id(blob_name)
    if old_doc_id == doc_id:
        logger.info("[ingest_trigger] Identical content (doc_id=%s) — skipping", doc_id)
        return

    if old_doc_id and old_doc_id != doc_id:
        logger.info(
            "[ingest_trigger] Update detected: old doc_id=%s → new doc_id=%s; cleanup queued",
            old_doc_id,
            doc_id,
        )
        await starter.start_new(
            "cleanup_orchestrator_fn",
            instance_id=f"cleanup-{old_doc_id}",
            client_input={"doc_id": old_doc_id, "blob_name": blob_name},
        )

    run_id = uuid.uuid4().hex[:12]
    ctx = PipelineContext(
        doc_id=doc_id,
        run_id=run_id,
        blob_name=blob_name,
        blob_url=blob_url,
    )

    store_doc_id_mapping(blob_name, doc_id)
    log_step_start("ingest_trigger", doc_id, run_id, blob_name=blob_name)

    instance_id = f"pipeline-{doc_id}-{run_id}"
    await starter.start_new(
        "pipeline_orchestrator_fn",
        instance_id=instance_id,
        client_input=ctx.model_dump(),
    )
    logger.info("[ingest_trigger] Started orchestrator instance: %s", instance_id)
