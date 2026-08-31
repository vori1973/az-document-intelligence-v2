"""Unit tests for grounded prompt construction, answer generation, and
citation mapping (task 2.5)."""

from __future__ import annotations

from unittest.mock import MagicMock

from rag.answer import (
    SYSTEM_PROMPT,
    build_grounded_messages,
    generate_answer,
    hits_to_citations,
)
from rag.contracts import QueryCitation

HITS = [
    {
        "id": "doc1-p3-para2",
        "type": "paragraph",
        "page": 3,
        "source_file": "/local/path/technical-guide.pdf",
        "text_for_embedding": "The recommended tire pressure is 32 psi.",
        "image_blob": None,
    },
    {
        "id": "doc1-p12-fig1",
        "type": "figure",
        "page": 12,
        "source_file": "/local/path/technical-guide.pdf",
        "text_for_embedding": "A diagram of the tire assembly.",
        "image_blob": "doc1/p12/fig1.png",
    },
]


def test_build_grounded_messages_includes_system_prompt_first():
    messages = build_grounded_messages("What is the tire pressure?", HITS)
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_build_grounded_messages_numbers_and_labels_each_source():
    messages = build_grounded_messages("What is the tire pressure?", HITS)
    user_message = messages[-1]["content"]
    assert "[1] (paragraph, page 3, technical-guide.pdf)" in user_message
    assert "[2] (figure, page 12, technical-guide.pdf)" in user_message
    assert "The recommended tire pressure is 32 psi." in user_message
    assert "Question: What is the tire pressure?" in user_message


def test_build_grounded_messages_includes_prior_history_between_system_and_question():
    history = [{"role": "user", "content": "earlier turn"}]
    messages = build_grounded_messages("follow-up?", HITS, history=history)
    assert messages[1] == {"role": "user", "content": "earlier turn"}
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"


def test_generate_answer_returns_text_and_token_usage():
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="The tire pressure is 32 psi. [1]"))
    ]
    client.chat.completions.create.return_value.usage = MagicMock(
        prompt_tokens=120, completion_tokens=18
    )

    result = generate_answer(client, "gpt-4o-mini", "What is the tire pressure?", HITS)

    assert result.text == "The tire pressure is 32 psi. [1]"
    assert result.input_tokens == 120
    assert result.output_tokens == 18
    client.chat.completions.create.assert_called_once()
    _, kwargs = client.chat.completions.create.call_args
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["temperature"] == 0


def test_generate_answer_tolerates_missing_usage():
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="answer text"))
    ]
    client.chat.completions.create.return_value.usage = None

    result = generate_answer(client, "gpt-4o-mini", "question", HITS)

    assert result.text == "answer text"
    assert result.input_tokens is None
    assert result.output_tokens is None


def test_generate_answer_propagates_sdk_failures_unchanged():
    """Matches `scripts/demo.py`'s `_answer` on failure; `rag.service`
    translates this into `DependencyError` for the Function App route."""
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("model unavailable")

    try:
        generate_answer(client, "gpt-4o-mini", "question", HITS)
        assert False, "expected RuntimeError to propagate"
    except RuntimeError as exc:
        assert str(exc) == "model unavailable"


def test_hits_to_citations_maps_raw_hits_to_typed_citations():
    citations = hits_to_citations(HITS)
    assert citations == [
        QueryCitation(source_file="technical-guide.pdf", page=3, type="paragraph", chunk_id="doc1-p3-para2", image_blob=None),
        QueryCitation(
            source_file="technical-guide.pdf",
            page=12,
            type="figure",
            chunk_id="doc1-p12-fig1",
            image_blob="doc1/p12/fig1.png",
        ),
    ]


def test_hits_to_citations_basenames_the_source_file():
    citations = hits_to_citations([HITS[0]])
    assert citations[0].source_file == "technical-guide.pdf"


def test_hits_to_citations_empty_when_no_hits():
    assert hits_to_citations([]) == []


def test_hits_to_citations_never_includes_retrieved_text():
    """Citations must never carry `text_for_embedding` — only identifying
    metadata (source file, page, type, chunk id, image blob)."""
    citations = hits_to_citations(HITS)
    for citation in citations:
        dumped = citation.model_dump()
        assert "text_for_embedding" not in dumped
        assert "The recommended tire pressure" not in str(dumped)

