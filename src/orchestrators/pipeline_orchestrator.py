"""
Durable Orchestrator — chains all 7 pipeline activities.

Activity sequence:
  step1_preanalysis → step2_adi → step3_router →
    [fan-out] extract_page × N (parallel) →
    [fan-out] ocr_page × N (parallel, capped) →
  step5_chunks → step6_embed → step7_search

Each activity reads its inputs from Blob artifacts written by the previous step.
The orchestrator only passes the PipelineContext (doc_id, run_id, blob_name, etc.).

Retry policy: 3 retries with exponential backoff on transient failures.
"""

from __future__ import annotations

import logging

import azure.durable_functions as df

logger = logging.getLogger(__name__)

RETRY_POLICY = df.RetryOptions(
    first_retry_interval_in_milliseconds=5_000,
    max_number_of_attempts=3,
)

OCR_BATCH_SIZE = 5  # max concurrent Mistral OCR calls (rate limit guard)


def pipeline_orchestrator(context: df.DurableOrchestrationContext):
    ctx: dict = context.get_input()
    doc_id = ctx["doc_id"]
    run_id = ctx["run_id"]

    logger.info("[orchestrator] Starting pipeline doc_id=%s run_id=%s", doc_id, run_id)

    # ── Step 1: Pre-analysis (SHA-256, page count, text heuristic) ───────
    yield context.call_activity_with_retry(
        "step1_preanalysis", RETRY_POLICY, ctx
    )

    # ── Step 2: Azure Document Intelligence (markdown, tables, figures) ──
    yield context.call_activity_with_retry(
        "step2_adi", RETRY_POLICY, ctx
    )

    # ── Step 3: Confidence-based routing decision ─────────────────────────
    routing_raw = yield context.call_activity_with_retry(
        "step3_router", RETRY_POLICY, ctx
    )
    pages_for_ocr: list[int] = routing_raw.get("pages_for_ocr", [])

    # ── Step 4: Fan-out OCR (extract page → SAS URL → Mistral OCR) ───────
    if pages_for_ocr:
        # Phase A: extract all pages in parallel (PyMuPDF → Blob)
        extract_tasks = [
            context.call_activity_with_retry(
                "extract_page", RETRY_POLICY, {**ctx, "page": p}
            )
            for p in pages_for_ocr
        ]
        sas_urls: list[str] = yield context.task_all(extract_tasks)

        # Phase B: OCR pages in parallel, capped at OCR_BATCH_SIZE concurrently
        page_sas_pairs = list(zip(pages_for_ocr, sas_urls))
        all_ocr_tasks = []
        for i in range(0, len(page_sas_pairs), OCR_BATCH_SIZE):
            batch = page_sas_pairs[i : i + OCR_BATCH_SIZE]
            batch_tasks = [
                context.call_activity_with_retry(
                    "ocr_page",
                    RETRY_POLICY,
                    {**ctx, "page": page, "sas_url": sas_url},
                )
                for page, sas_url in batch
            ]
            yield context.task_all(batch_tasks)
            all_ocr_tasks.extend(batch_tasks)

    # ── Step 5: Build RAG chunks (table_row / paragraph / figure) ────────
    yield context.call_activity_with_retry(
        "step5_chunks", RETRY_POLICY, ctx
    )

    # ── Step 6: Embed chunks (Azure OpenAI text-embedding-ada-002) ───────
    yield context.call_activity_with_retry(
        "step6_embed", RETRY_POLICY, ctx
    )

    # ── Step 7: Index into Azure AI Search ───────────────────────────────
    yield context.call_activity_with_retry(
        "step7_search", RETRY_POLICY, ctx
    )

    logger.info("[orchestrator] Pipeline complete doc_id=%s run_id=%s", doc_id, run_id)
    return {"status": "completed", "doc_id": doc_id, "run_id": run_id}


def cleanup_orchestrator(context: df.DurableOrchestrationContext):
    """Standalone orchestrator for stale-chunk cleanup triggered on document update."""
    inp: dict = context.get_input()
    doc_id = inp["doc_id"]
    blob_name = inp["blob_name"]

    yield context.call_activity_with_retry(
        "cleanup_activity",
        RETRY_POLICY,
        {"doc_id": doc_id, "blob_name": blob_name},
    )
    return {"status": "cleaned", "doc_id": doc_id}


