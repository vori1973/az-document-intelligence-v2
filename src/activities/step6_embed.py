"""
Step 6 — Generate embeddings.

Reads chunks.json from Blob Storage, batches chunks of 100,
calls Azure OpenAI text-embedding-ada-002 via the openai SDK,
writes chunks-embedded.json.

Auth: DefaultAzureCredential via azure_ad_token_provider.
      Function App MI must have Cognitive Services OpenAI User on the AOAI resource.

Ported from v1 step6-embed.ts.
"""

from __future__ import annotations

import logging
import os
import time

from openai import AzureOpenAI

from shared.auth import get_openai_token_provider
from shared.blob_client import download_json_artifact, upload_json_artifact
from shared.telemetry import timed_step, track_metric
from models.types import RagChunk

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
RETRY_DELAYS = [2.0, 4.0, 8.0, 16.0]
AOAI_ENDPOINT = os.environ.get("AOAI_ENDPOINT", "")
EMBEDDING_DEPLOYMENT = os.environ.get("AOAI_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002")


def _get_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=AOAI_ENDPOINT,
        azure_ad_token_provider=get_openai_token_provider(),
        api_version="2023-05-15",
    )


def _embed_batch(client: AzureOpenAI, texts: list[str]) -> list[list[float]]:
    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay:
            logger.warning("[step6] rate limited, retrying in %.0fs", delay)
            time.sleep(delay)
        try:
            response = client.embeddings.create(model=EMBEDDING_DEPLOYMENT, input=texts)
            return [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
        except Exception as exc:
            if "429" in str(exc) and attempt < len(RETRY_DELAYS):
                continue
            raise
    raise RuntimeError("Embedding API: exceeded max retries")


def step6_embed_main(ctx: dict) -> dict:
    doc_id: str = ctx["doc_id"]
    run_id: str = ctx["run_id"]

    with timed_step("step6_embed", doc_id, run_id):
        chunks_raw = download_json_artifact(doc_id, run_id, "chunks.json")
        chunks = [RagChunk.model_validate(c) for c in chunks_raw]

        client = _get_client()
        total_batches = (len(chunks) + BATCH_SIZE - 1) // BATCH_SIZE
        total_tokens = 0

        for b_start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[b_start : b_start + BATCH_SIZE]
            texts = [c.text_for_embedding for c in batch]
            batch_num = b_start // BATCH_SIZE + 1
            logger.info("[step6] Batch %d/%d — %d chunks", batch_num, total_batches, len(batch))

            embeddings = _embed_batch(client, texts)
            for chunk, embedding in zip(batch, embeddings):
                chunk.embedding = embedding
            total_tokens += sum(len(t.split()) for t in texts)  # approximate

        upload_json_artifact(doc_id, run_id, "chunks-embedded.json", [c.model_dump() for c in chunks])

        track_metric("embedding_tokens_approx", total_tokens, doc_id=doc_id)
        logger.info(
            "[step6] doc_id=%s chunks=%d batches=%d",
            doc_id, len(chunks), total_batches,
        )
        return {"chunks_embedded": len(chunks)}
