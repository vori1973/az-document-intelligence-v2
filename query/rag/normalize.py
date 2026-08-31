"""
Exact normalization, hashing, and cache identity (task 2.3).

Implements the documented contract from
`openspec/changes/add-apim-exact-cache-demo/design.md`
("Use custom key/value policies for POST exact caching"):

    rag-response:v1:
      scope:{securityScope}:
      generation:{knowledgeGeneration}:
      prompt:{promptVersion}:
      model:{logicalModelVersion}:
      query:{normalizedQuestionHash}

Only an opaque, further-hashed key ID is meant to leave the process boundary
(headers/telemetry) — see `cache_key_id`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

CACHE_KEY_PREFIX = "rag-response:v1"
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_question(question: str) -> str:
    """Trim, lowercase (Unicode-preserving), and collapse internal whitespace.

    `str.lower()` is used rather than `casefold()` or an ASCII-only lowering
    so non-Latin scripts are preserved rather than stripped or mangled.
    """
    collapsed = _WHITESPACE_RE.sub(" ", question.strip())
    return collapsed.lower()


def hash_normalized_question(normalized_question: str) -> str:
    """SHA-256 hex digest of the normalized question (never the raw text)."""
    return hashlib.sha256(normalized_question.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheIdentity:
    """Every dimension that materially changes the answer, plus the derived
    opaque key and short key ID. `cache_key` is not raw-sensitive (it never
    contains the question itself, only its hash and version labels) but per
    the design decision only `key_id` is meant to be exposed externally.
    """

    normalized_question_hash: str
    knowledge_generation: str
    security_scope: str
    prompt_version: str
    logical_model_version: str
    cache_key: str
    key_id: str


def build_cache_identity(
    *,
    question: str,
    knowledge_generation: str,
    security_scope: str,
    prompt_version: str,
    logical_model_version: str,
) -> CacheIdentity:
    """Derive the full cache identity for a validated, trusted request."""
    normalized = normalize_question(question)
    question_hash = hash_normalized_question(normalized)
    cache_key = (
        f"{CACHE_KEY_PREFIX}:"
        f"scope:{security_scope}:"
        f"generation:{knowledge_generation}:"
        f"prompt:{prompt_version}:"
        f"model:{logical_model_version}:"
        f"query:{question_hash}"
    )
    key_id = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
    return CacheIdentity(
        normalized_question_hash=question_hash,
        knowledge_generation=knowledge_generation,
        security_scope=security_scope,
        prompt_version=prompt_version,
        logical_model_version=logical_model_version,
        cache_key=cache_key,
        key_id=key_id,
    )
