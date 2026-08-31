"""Unit tests for exact normalization, hashing, and cache identity (task 2.5).

Test vectors here are the documented normalization/cache-identity contract
from `openspec/changes/add-apim-exact-cache-demo/design.md` ("Use custom
key/value policies for POST exact caching"). The APIM policy in
`infra/policies/rag-api.xml` reproduces the same algorithm in C#;
`tests/infra/test_apim_policies.py` asserts the two have not drifted.
"""

from __future__ import annotations

from rag.normalize import (
    build_cache_identity,
    hash_normalized_question,
    normalize_question,
)


def test_normalize_question_trims_and_lowercases():
    assert normalize_question("  What Is The Tire Pressure?  ") == "what is the tire pressure?"


def test_normalize_question_collapses_internal_whitespace():
    assert normalize_question("What   is\tthe\n\ntire pressure?") == "what is the tire pressure?"


def test_normalize_question_is_unicode_preserving():
    """Non-Latin scripts must be preserved by lowering, not stripped or
    replaced (unlike an ASCII-only lowering)."""
    assert normalize_question("Ünïcödé Qüestion") == "ünïcödé qüestion"
    assert normalize_question("  日本語のテスト  ") == "日本語のテスト"


def test_normalize_question_equivalent_variants_match():
    variant_a = "What is the tire pressure?"
    variant_b = "  what   IS the tire\npressure?  "
    assert normalize_question(variant_a) == normalize_question(variant_b)


def test_hash_normalized_question_is_deterministic_sha256():
    normalized = normalize_question("What is the tire pressure?")
    assert hash_normalized_question(normalized) == hash_normalized_question(normalized)
    # SHA-256 hex digest is exactly 64 characters.
    assert len(hash_normalized_question(normalized)) == 64


def test_hash_normalized_question_differs_for_different_text():
    assert hash_normalized_question("question one") != hash_normalized_question("question two")


BASE_DIMENSIONS = dict(
    knowledge_generation="17",
    security_scope="demo-public",
    prompt_version="v1",
    logical_model_version="v1",
)


def test_build_cache_identity_equivalent_normalized_question_matches():
    """Spec scenario: 'Equivalent normalized question' — two requests that
    differ only by documented whitespace/case normalization resolve to the
    same cache identity."""
    identity_a = build_cache_identity(question="What is the tire pressure?", **BASE_DIMENSIONS)
    identity_b = build_cache_identity(
        question="  what   IS the tire\npressure?  ", **BASE_DIMENSIONS
    )
    assert identity_a.cache_key == identity_b.cache_key
    assert identity_a.key_id == identity_b.key_id


def test_build_cache_identity_material_dimension_changes_differ():
    """Spec scenario: 'Material cache dimension changes' — normalized
    question, generation, scope, prompt version, or model version differing
    resolves to different cache identities."""
    base = build_cache_identity(question="What is the tire pressure?", **BASE_DIMENSIONS)

    different_question = build_cache_identity(
        question="What is the oil capacity?", **BASE_DIMENSIONS
    )
    different_generation = build_cache_identity(
        question="What is the tire pressure?", **{**BASE_DIMENSIONS, "knowledge_generation": "18"}
    )
    different_scope = build_cache_identity(
        question="What is the tire pressure?", **{**BASE_DIMENSIONS, "security_scope": "other-scope"}
    )
    different_prompt = build_cache_identity(
        question="What is the tire pressure?", **{**BASE_DIMENSIONS, "prompt_version": "v2"}
    )
    different_model = build_cache_identity(
        question="What is the tire pressure?",
        **{**BASE_DIMENSIONS, "logical_model_version": "v2"},
    )

    variants = [
        different_question,
        different_generation,
        different_scope,
        different_prompt,
        different_model,
    ]
    for variant in variants:
        assert variant.cache_key != base.cache_key
        assert variant.key_id != base.key_id


def test_cache_key_contains_documented_namespace_and_dimensions():
    identity = build_cache_identity(question="What is the tire pressure?", **BASE_DIMENSIONS)
    assert identity.cache_key.startswith("rag-response:v1:")
    assert "scope:demo-public:" in identity.cache_key
    assert "generation:17:" in identity.cache_key
    assert "prompt:v1:" in identity.cache_key
    assert "model:v1:" in identity.cache_key
    assert identity.cache_key.endswith(f"query:{identity.normalized_question_hash}")


def test_cache_key_never_contains_raw_question_text():
    """Cache identifiers must be opaque: the full cache key contains only the
    question's hash and version labels, never the raw text itself."""
    identity = build_cache_identity(question="What is the tire pressure?", **BASE_DIMENSIONS)
    assert "tire" not in identity.cache_key
    assert "pressure" not in identity.cache_key


def test_key_id_is_a_short_opaque_hash():
    identity = build_cache_identity(question="What is the tire pressure?", **BASE_DIMENSIONS)
    assert len(identity.key_id) == 16
    int(identity.key_id, 16)  # must be valid hex
