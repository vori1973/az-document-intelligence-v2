"""
Grounded prompt construction, answer generation, and citation mapping
(task 2.1 / 2.5).

`SYSTEM_PROMPT` and `build_grounded_messages` are extracted unchanged in
behavior from `scripts/demo.py`'s `SYSTEM`/`_answer` (task 2.1).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from openai import AzureOpenAI

from .contracts import QueryCitation, RetrievedChunk

SYSTEM_PROMPT = (
    "You answer questions about technical documents using ONLY the numbered "
    "sources provided. Cite every claim as [n]. Sources marked [Figure] came from a "
    "vision model reading the image — when you use one, say which page's figure it was. "
    "If the sources do not contain the answer, say so plainly rather than guessing."
)


def build_grounded_messages(
    question: str,
    hits: list[dict],
    history: list[dict] | None = None,
) -> list[dict]:
    """Build the chat message list from raw Search hits, matching
    `scripts/demo.py`'s `_answer` context format exactly."""
    context = "\n\n".join(
        f"[{i + 1}] ({d['type']}, page {d['page']}, {os.path.basename(d['source_file'])})"
        f"\n{d.get('text_for_embedding', '')}"
        for i, d in enumerate(hits)
    )
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history or []
    messages.append({"role": "user", "content": f"Sources:\n{context}\n\nQuestion: {question}"})
    return messages


@dataclass(frozen=True)
class AnswerResult:
    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


def generate_answer(
    client: AzureOpenAI,
    model: str,
    question: str,
    hits: list[dict],
    history: list[dict] | None = None,
    *,
    temperature: float = 0,
) -> AnswerResult:
    """Invoke the chat model with the grounded prompt, matching
    `scripts/demo.py`'s `_answer` behavior on success or failure exactly
    (`rag.service` translates a failure into a `DependencyError`). Reports
    token usage when the SDK response provides it."""
    messages = build_grounded_messages(question, hits, history)
    response = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature
    )

    usage = getattr(response, "usage", None)
    return AnswerResult(
        text=response.choices[0].message.content,
        input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
    )


def hits_to_citations(hits: list[dict]) -> list[QueryCitation]:
    """Pure mapping from raw Search hits (or typed `RetrievedChunk`s) to
    response citations (task 2.1 / 2.5)."""
    citations = []
    for hit in hits:
        chunk = hit if isinstance(hit, RetrievedChunk) else RetrievedChunk.model_validate(
            {
                "id": hit.get("id", ""),
                "type": hit.get("type", ""),
                "page": hit.get("page", 0),
                "source_file": hit.get("source_file", ""),
                "document_id": hit.get("document_id"),
                "image_blob": hit.get("image_blob"),
                "text_for_embedding": hit.get("text_for_embedding") or "",
                "score": hit.get("@search.score"),
            }
        )
        citations.append(
            QueryCitation(
                source_file=os.path.basename(chunk.source_file),
                page=chunk.page,
                type=chunk.type,
                chunk_id=chunk.id or None,
                image_blob=chunk.image_blob,
            )
        )
    return citations
