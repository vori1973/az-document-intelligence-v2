"""
Step 4C — One-pass figure understanding.

One schema-enforced vision call per surviving figure candidate. Qualification
and verbalization are combined into a single request so the two cannot
disagree, and so each figure costs exactly one call.

The model produces *retrieval metadata*, never source text and never
citations. ADI keeps ownership of page, polygon, and figure index; anything
the model returns is additive and is discarded if it fails the schema.

Grounding is enforced in the prompt: the model is told to describe only what
is visible and to declare unreadable text rather than guess at it.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from openai import AzureOpenAI

from shared.auth import get_openai_token_provider
from shared.blob_client import download_artifact, download_json_artifact, upload_json_artifact
from shared.telemetry import timed_step, track_metric
from models.types import FigureCandidate

logger = logging.getLogger(__name__)

AOAI_ENDPOINT = os.environ.get("AOAI_ENDPOINT", "")
FIGURE_MODEL = os.environ.get("FIGURE_UNDERSTANDING_MODEL", "gpt-4o-mini")
MAX_CONCURRENT = int(os.environ.get("FIGURE_MAX_CONCURRENT", "4"))
MAX_FIGURES = int(os.environ.get("FIGURE_MAX_PER_DOC", "60"))
API_VERSION = "2024-10-21"

RETRY_DELAYS = [2.0, 4.0, 8.0]

CATEGORIES = [
    "device_photo", "device_component", "procedure_illustration",
    "anatomical_illustration", "diagram", "chart", "table_like",
    "safety_symbol", "screenshot", "logo", "decorative",
    "header_footer", "background", "unknown",
]

FIGURE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_meaningful": {"type": "boolean"},
        "category": {"type": "string", "enum": CATEGORIES},
        "model_confidence_label": {"type": "string", "enum": ["high", "medium", "low"]},
        "contains_text": {"type": "boolean"},
        "short_description": {"type": "string"},
        "visible_labels": {"type": "array", "items": {"type": "string"}},
        "device_or_component_terms": {"type": "array", "items": {"type": "string"}},
        "procedure_actions": {"type": "array", "items": {"type": "string"}},
        "warnings_or_constraints": {"type": "array", "items": {"type": "string"}},
        "search_keywords": {"type": "array", "items": {"type": "string"}},
        "uncertainty": {"type": "array", "items": {"type": "string"}},
        "needs_larger_context_crop": {"type": "boolean"},
    },
    "required": [
        "is_meaningful", "category", "model_confidence_label", "contains_text",
        "short_description", "visible_labels", "device_or_component_terms",
        "procedure_actions", "warnings_or_constraints", "search_keywords",
        "uncertainty", "needs_larger_context_crop",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You classify and describe figures extracted from technical and medical documents so they can be retrieved by search.

Describe only what is visibly present in the image. You must not invent:
- device identity or model number
- procedure sequence
- clinical recommendation
- measurements or settings
- warnings not visible in the image or the supplied context
- component names unsupported by visible labels or the supplied context

If text in the image is unreadable, say so in `uncertainty` rather than guessing.

Set is_meaningful = false for page furniture, rules, separators, decorative
flourishes, and standalone logos. Set it to true for anything a reader might
search for: device photos, components, procedure or anatomical illustrations,
diagrams, charts, screenshots, and safety symbols.

`short_description` must be one sentence. `search_keywords` should be terms a
user would plausibly type to find this figure."""


def _get_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=AOAI_ENDPOINT,
        azure_ad_token_provider=get_openai_token_provider(),
        api_version=API_VERSION,
    )


def _build_user_content(candidate: FigureCandidate, image_b64: str) -> list[dict]:
    context_lines = [f"Page: {candidate.page}"]
    if candidate.caption:
        context_lines.append(f"ADI caption: {candidate.caption}")
    else:
        context_lines.append("ADI caption: (none detected)")
    if candidate.routing_signals:
        context_lines.append(f"Routing signals: {', '.join(candidate.routing_signals)}")
    if candidate.features:
        context_lines.append(
            f"Occupies {candidate.features.area_ratio:.1%} of the page "
            f"(aspect ratio {candidate.features.aspect_ratio:.1f})"
        )

    return [
        {"type": "text", "text": "\n".join(context_lines)},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"},
        },
    ]


def _understand_one(
    client: AzureOpenAI, doc_id: str, run_id: str, candidate: FigureCandidate
) -> dict | None:
    """Run one schema-enforced vision call. Returns None if it cannot be trusted."""
    if not candidate.tight_crop_uri:
        return None

    try:
        image_bytes = download_artifact(doc_id, run_id, candidate.tight_crop_uri)
    except Exception:
        logger.warning("[step4c] crop missing for p%d-fig%d",
                       candidate.page, candidate.figure_index)
        return None

    image_b64 = base64.b64encode(image_bytes).decode()

    for attempt, delay in enumerate([0.0] + RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            response = client.chat.completions.create(
                model=FIGURE_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_content(candidate, image_b64)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "figure_understanding",
                        "schema": FIGURE_SCHEMA,
                        "strict": True,
                    },
                },
                temperature=0,
                max_tokens=700,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as exc:
            transient = "429" in str(exc) or "503" in str(exc) or "timeout" in str(exc).lower()
            if transient and attempt < len(RETRY_DELAYS):
                logger.warning("[step4c] transient error, retrying: %s", exc)
                continue
            logger.error(
                "[step4c] understanding failed p%d-fig%d: %s",
                candidate.page, candidate.figure_index, exc,
            )
            return None
    return None


def _routing_outcome(understanding: dict | None) -> str:
    """Map the model output onto the retain/reject decision.

    Only a confident 'not meaningful' rejects. Anything uncertain is retained
    so that recall is never traded away on a low-confidence guess.
    """
    if understanding is None:
        return "retain_unverified"
    if not understanding.get("is_meaningful"):
        if understanding.get("model_confidence_label") == "high":
            return "reject"
        return "retain_low_confidence"
    return "retain"


def step4c_understanding_main(ctx: dict) -> dict:
    doc_id: str = ctx["doc_id"]
    run_id: str = ctx["run_id"]

    with timed_step("step4c_understanding", doc_id, run_id):
        raw = download_json_artifact(doc_id, run_id, "figures.json")
        candidates = [FigureCandidate.model_validate(c) for c in raw]
        qualified = [
            c for c in candidates if c.status == "candidate" and c.tight_crop_uri
        ][:MAX_FIGURES]

        if not qualified:
            upload_json_artifact(doc_id, run_id, "figure-understanding.json", [])
            upload_json_artifact(doc_id, run_id, "step4c-result.json", {
                "understood": 0, "retained": 0, "rejected": 0,
            })
            logger.info("[step4c] doc_id=%s no qualified figures", doc_id)
            return {"understood": 0, "retained": 0}

        client = _get_client()
        t0 = time.monotonic()

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as pool:
            understandings = list(pool.map(
                lambda c: _understand_one(client, doc_id, run_id, c), qualified
            ))

        records = []
        outcomes: dict[str, int] = {}
        for candidate, understanding in zip(qualified, understandings):
            outcome = _routing_outcome(understanding)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            records.append({
                "page": candidate.page,
                "figure_index": candidate.figure_index,
                "figure_id": candidate.figure_id,
                "tight_crop_uri": candidate.tight_crop_uri,
                "caption": candidate.caption,
                "bounding_polygon": candidate.bounding_polygon,
                "routing_outcome": outcome,
                "understanding": understanding,
            })

        duration_ms = (time.monotonic() - t0) * 1000
        retained = sum(v for k, v in outcomes.items() if k != "reject")

        upload_json_artifact(doc_id, run_id, "figure-understanding.json", records)
        upload_json_artifact(doc_id, run_id, "step4c-result.json", {
            "understood": len(records),
            "retained": retained,
            "rejected": outcomes.get("reject", 0),
            "outcomes": outcomes,
            "model": FIGURE_MODEL,
            "duration_ms": round(duration_ms),
        })

        track_metric("figures_understood", len(records), doc_id=doc_id)
        track_metric("figures_retained", retained, doc_id=doc_id)

        logger.info(
            "[step4c] doc_id=%s understood=%d retained=%d outcomes=%s %.0fms",
            doc_id, len(records), retained, outcomes, duration_ms,
        )
        return {"understood": len(records), "retained": retained}
