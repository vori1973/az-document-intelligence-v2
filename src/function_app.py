"""
Azure Functions entry point.

Registers all triggers, orchestrators, and activity functions.
The Azure Functions Python v2 programming model uses decorators on a single
function_app.py to declare all functions.
"""

import azure.durable_functions as df
import azure.functions as func

from triggers.ingest_trigger import ingest_trigger_main
from triggers.delete_trigger import delete_trigger_main
from orchestrators.pipeline_orchestrator import (
    pipeline_orchestrator,
    cleanup_orchestrator,
)
from activities.step1_preanalysis import step1_preanalysis_main
from activities.step2_adi import step2_adi_main
from activities.step3_router import step3_router_main
from activities.step4_ocr import extract_page_main, ocr_page_main
from activities.step4a_figures import step4a_figures_main
from activities.step4c_understanding import step4c_understanding_main
from activities.step5_chunks import step5_chunks_main
from activities.step6_embed import step6_embed_main
from activities.step7_search import step7_search_main

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# ── Event Grid Triggers ───────────────────────────────────────────────────


@app.event_grid_trigger(arg_name="event")
@app.durable_client_input(client_name="starter")
async def ingest_trigger(event: func.EventGridEvent, starter: str) -> None:
    await ingest_trigger_main(event, starter)


@app.event_grid_trigger(arg_name="event")
async def delete_trigger(event: func.EventGridEvent) -> None:
    await delete_trigger_main(event)


# ── Durable Orchestrators ─────────────────────────────────────────────────


@app.orchestration_trigger(context_name="context")
def pipeline_orchestrator_fn(context: df.DurableOrchestrationContext):
    yield from pipeline_orchestrator(context)


@app.orchestration_trigger(context_name="context")
def cleanup_orchestrator_fn(context: df.DurableOrchestrationContext):
    yield from cleanup_orchestrator(context)


# ── Activity Functions ────────────────────────────────────────────────────


@app.activity_trigger(input_name="ctx")
def step1_preanalysis(ctx: dict) -> dict:
    return step1_preanalysis_main(ctx)


@app.activity_trigger(input_name="ctx")
def step2_adi(ctx: dict) -> dict:
    return step2_adi_main(ctx)


@app.activity_trigger(input_name="ctx")
def step3_router(ctx: dict) -> dict:
    return step3_router_main(ctx)


@app.activity_trigger(input_name="ctx")
def extract_page(ctx: dict) -> str:
    return extract_page_main(ctx)


@app.activity_trigger(input_name="ctx")
def ocr_page(ctx: dict) -> dict:
    return ocr_page_main(ctx)


@app.activity_trigger(input_name="ctx")
def step4a_figures(ctx: dict) -> dict:
    return step4a_figures_main(ctx)


@app.activity_trigger(input_name="ctx")
def step4c_understanding(ctx: dict) -> dict:
    return step4c_understanding_main(ctx)


@app.activity_trigger(input_name="ctx")
def step5_chunks(ctx: dict) -> dict:
    return step5_chunks_main(ctx)


@app.activity_trigger(input_name="ctx")
def step6_embed(ctx: dict) -> dict:
    return step6_embed_main(ctx)


@app.activity_trigger(input_name="ctx")
def step7_search(ctx: dict) -> dict:
    return step7_search_main(ctx)


@app.activity_trigger(input_name="ctx")
def cleanup_activity(ctx: dict) -> dict:
    from shared.blob_client import delete_doc_artifacts
    from triggers.delete_trigger import _delete_search_chunks

    doc_id = ctx["doc_id"]
    chunk_count = _delete_search_chunks(doc_id)
    blob_count = delete_doc_artifacts(doc_id)
    return {"chunks_deleted": chunk_count, "blobs_deleted": blob_count}
