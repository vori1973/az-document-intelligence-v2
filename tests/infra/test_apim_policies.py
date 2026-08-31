"""APIM policy contract tests (tasks 5.3 - 5.7, 6.1).

The gateway policies and `query/rag/normalize.py` implement the same cache
identity in two languages. These tests read the checked-in policy XML and assert
the observable contract the spec depends on:

  * baseline is genuinely uncached and the built-in operation genuinely caches;
  * the trusted cache dimensions come from deployment configuration, never from
    the caller;
  * the cache key is byte-for-byte the layout produced by
    `rag.normalize.build_cache_identity`;
  * only eligible 2xx JSON responses are stored;
  * every response carries the cache/correlation proof headers; and
  * nothing sensitive is exposed in a header.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

import pytest

from rag.normalize import CACHE_KEY_PREFIX, build_cache_identity

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
POLICY_DIR = os.path.join(REPO_ROOT, "infra", "policies")

API_POLICY = os.path.join(POLICY_DIR, "rag-api.xml")
BASELINE_POLICY = os.path.join(POLICY_DIR, "rag-baseline.xml")
BUILT_IN_POLICY = os.path.join(POLICY_DIR, "rag-apim-built-in.xml")

ALL_POLICIES = [API_POLICY, BASELINE_POLICY, BUILT_IN_POLICY]

TRUSTED_REQUEST_HEADERS = [
    "X-Demo-Generation",
    "X-Demo-Security-Scope",
    "X-Demo-Prompt-Version",
    "X-Demo-Model-Version",
    "X-Demo-Cache-Mode",
    "X-Demo-Correlation-Id",
]

PROOF_RESPONSE_HEADERS = [
    "x-demo-cache",
    "x-demo-cache-type",
    "x-demo-generation",
    "x-demo-cache-key-id",
    "x-demo-correlation-id",
]


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def parse(path: str) -> ET.Element:
    return ET.parse(path).getroot()


def section(root: ET.Element, name: str) -> ET.Element:
    found = root.find(name)
    assert found is not None, f"missing <{name}> section"
    return found


def descendants(element: ET.Element, tag: str) -> list[ET.Element]:
    return list(element.iter(tag))


def set_headers(element: ET.Element) -> dict[str, str]:
    """Map of header name -> concatenated <value> text for every set-header."""
    headers = {}
    for header in element.iter("set-header"):
        name = header.get("name")
        values = "".join((child.text or "") for child in header.findall("value"))
        headers[name] = values
    return headers


# ── Shape ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ALL_POLICIES)
def test_policy_is_well_formed_with_all_four_sections(path):
    root = parse(path)
    assert root.tag == "policies"
    assert [child.tag for child in root] == ["inbound", "backend", "outbound", "on-error"]


@pytest.mark.parametrize("path", [BASELINE_POLICY, BUILT_IN_POLICY])
def test_operation_policies_inherit_every_section(path):
    """Dropping a <base /> silently removes validation, trusted headers, or
    backend authentication from that section."""
    root = parse(path)
    for name in ("inbound", "backend", "outbound", "on-error"):
        assert section(root, name).find("base") is not None, f"{path}: <{name}> lost <base />"


# ── Trusted context (spec: "Caller supplies cache partition values") ──────


def test_api_policy_overwrites_every_trusted_header():
    inbound = section(parse(API_POLICY), "inbound")
    overrides = {
        header.get("name"): header.get("exists-action")
        for header in inbound.findall("set-header")
    }
    for name in TRUSTED_REQUEST_HEADERS:
        assert overrides.get(name) == "override", f"{name} must be overwritten, not appended"


def test_api_policy_strips_caller_credentials_before_forwarding():
    inbound = section(parse(API_POLICY), "inbound")
    deleted = {
        header.get("name")
        for header in inbound.findall("set-header")
        if header.get("exists-action") == "delete"
    }
    assert "Authorization" in deleted
    assert "Ocp-Apim-Subscription-Key" in deleted


def test_trusted_dimensions_come_from_named_values_not_the_request_body():
    text = read(API_POLICY)
    for named_value in (
        "{{rag-knowledge-generation}}",
        "{{rag-security-scope}}",
        "{{rag-prompt-version}}",
        "{{rag-logical-model-version}}",
    ):
        assert named_value in text
    # The parsed request body is only ever read for the question itself.
    body_reads = re.findall(r'body\["([a-zA-Z]+)"\]', text)
    assert set(body_reads) == {"question"}


def test_correlation_id_is_gateway_generated():
    text = read(API_POLICY)
    assert 'value="@(context.RequestId.ToString())"' in text


# ── Bounded JSON body handling (task 5.4) ────────────────────────────────


def test_api_policy_bounds_media_type_body_size_and_question_length():
    text = read(API_POLICY)
    assert "application/json" in text
    assert "{{rag-max-request-bytes}}" in text
    assert "{{rag-max-question-length}}" in text

    statuses = {
        status.get("code")
        for status in parse(API_POLICY).iter("set-status")
    }
    assert {"415", "413", "400"}.issubset(statuses)


def test_malformed_body_does_not_throw_out_of_the_policy():
    """A parse failure must degrade to a rejected request, not a 500."""
    text = read(API_POLICY)
    assert text.count("catch (Exception)") >= 3
    assert "JObject.Parse" in text


# ── Cache identity (spec: "Exact and opaque cache identity") ─────────────


def test_policy_cache_key_layout_matches_the_python_contract():
    """The exact string the policy concatenates must equal the layout produced
    by rag.normalize.build_cache_identity, with named values standing in for the
    deployment-managed dimensions."""
    identity = build_cache_identity(
        question="any question",
        knowledge_generation="{{rag-knowledge-generation}}",
        security_scope="{{rag-security-scope}}",
        prompt_version="{{rag-prompt-version}}",
        logical_model_version="{{rag-logical-model-version}}",
    )
    expected_prefix = identity.cache_key[: -len(identity.normalized_question_hash)]

    assert expected_prefix.startswith(CACHE_KEY_PREFIX)
    assert expected_prefix in read(API_POLICY), (
        "APIM cache key layout drifted from rag.normalize.build_cache_identity; "
        f"expected the policy to contain {expected_prefix!r}"
    )


def test_policy_normalization_matches_the_documented_algorithm():
    text = read(API_POLICY)
    # trim -> collapse whitespace runs -> Unicode-preserving lowercase
    assert 'Regex.Replace(raw.Trim(), @"\\s+", " ").ToLowerInvariant()' in text
    # SHA-256 over UTF-8 bytes, rendered as lowercase hex
    assert "System.Security.Cryptography.SHA256.Create()" in text
    assert "System.Text.Encoding.UTF8.GetBytes(normalized)" in text
    assert 'BitConverter.ToString(digest).Replace("-", string.Empty).ToLowerInvariant()' in text


def test_exposed_key_id_length_matches_the_python_key_id():
    identity = build_cache_identity(
        question="any question",
        knowledge_generation="1",
        security_scope="demo-public",
        prompt_version="v1",
        logical_model_version="v1",
    )
    assert f"Substring(0, {len(identity.key_id)})" in read(API_POLICY)


# ── Baseline is uncached; built-in caches (spec: "Comparable APIM operations") ──


def test_baseline_operation_has_no_cache_policy():
    """Checked structurally rather than textually: the file's comments name the
    cache policies it deliberately omits."""
    root = parse(BASELINE_POLICY)
    for tag in ("cache-lookup-value", "cache-store-value", "cache-lookup", "cache-store"):
        assert descendants(root, tag) == [], f"baseline must not use <{tag}>"


def test_built_in_operation_looks_up_and_stores_exactly_once():
    root = parse(BUILT_IN_POLICY)
    lookups = descendants(root, "cache-lookup-value")
    stores = descendants(root, "cache-store-value")
    assert len(lookups) == 1
    assert len(stores) == 1
    # Both sides address the same key and the tier's built-in cache.
    assert lookups[0].get("key") == stores[0].get("key")
    assert lookups[0].get("caching-type") == "internal"
    assert stores[0].get("caching-type") == "internal"
    assert stores[0].get("duration") == "{{rag-cache-ttl-seconds}}"


def test_lookup_only_runs_for_eligible_requests():
    root = parse(BUILT_IN_POLICY)
    lookup = descendants(root, "cache-lookup-value")[0]
    guard = None
    for when in root.iter("when"):
        if when.find("cache-lookup-value") is not None:
            guard = when.get("condition")
    assert guard is not None, "cache lookup must be guarded"
    assert "cacheEligible" in guard
    assert lookup.get("variable-name") == "cachedEnvelope"


def test_only_eligible_successful_json_responses_are_stored():
    """spec: "Backend error response" and "Successful eligible response"."""
    root = parse(BUILT_IN_POLICY)
    store_condition = None
    for when in root.iter("when"):
        if when.find("cache-store-value") is not None:
            store_condition = when.get("condition")
    assert store_condition is not None

    assert 'GetValueOrDefault<string>("cacheOutcome", "") == "MISS"' in store_condition
    assert 'GetValueOrDefault<bool>("cacheEligible", false)' in store_condition
    assert "context.Response.StatusCode >= 200" in store_condition
    assert "context.Response.StatusCode < 300" in store_condition
    assert "application/json" in store_condition
    assert "{{rag-max-cached-response-bytes}}" in store_condition


def test_cache_hit_short_circuits_the_backend():
    root = parse(BUILT_IN_POLICY)
    hit_branches = [
        when
        for when in root.iter("when")
        if when.find("return-response") is not None and "cachedBody" in (when.get("condition") or "")
    ]
    assert len(hit_branches) == 1
    hit = hit_branches[0]
    headers = set_headers(hit)
    assert headers["x-demo-cache"] == "HIT"
    assert headers["x-demo-cache-type"] == "apim-built-in"
    # The cached payload's own execution metadata belongs to the earlier
    # invocation, so the current-request header is removed and the producing
    # invocation is reported under a distinct name.
    assert "x-demo-cached-backend-invocation-id" in headers
    deleted = {
        header.get("name")
        for header in hit.iter("set-header")
        if header.get("exists-action") == "delete"
    }
    assert "x-demo-backend-invocation-id" in deleted
    assert "Server-Timing" in deleted


# ── Failure behavior (task 5.7) ──────────────────────────────────────────


def test_cache_failure_falls_back_to_a_protected_backend_call():
    root = parse(BUILT_IN_POLICY)
    inbound = section(root, "inbound")

    # A miss (including "the cache was unavailable") continues to the backend,
    # while a request that never became eligible stays a bypass.
    otherwise_bodies = [
        otherwise
        for otherwise in inbound.iter("otherwise")
        if otherwise.find("set-variable") is not None
    ]
    outcome_values = [
        variable.get("value")
        for otherwise in otherwise_bodies
        for variable in otherwise.findall("set-variable")
        if variable.get("name") == "cacheOutcome"
    ]
    assert len(outcome_values) == 1
    assert '"MISS"' in outcome_values[0]
    assert '"BYPASS"' in outcome_values[0]
    assert "cacheEligible" in outcome_values[0]
    # ... and never as a successful empty response: the hit branch requires a
    # non-empty cached body.
    assert any(
        "!string.IsNullOrEmpty" in (when.get("condition") or "")
        for when in inbound.iter("when")
        if when.find("return-response") is not None
    )


@pytest.mark.parametrize("path", [BASELINE_POLICY, BUILT_IN_POLICY])
def test_backend_is_rate_limited_on_both_operations(path):
    root = parse(path)
    limits = descendants(root, "rate-limit-by-key")
    assert len(limits) == 1
    limit = limits[0]
    assert limit.get("calls") == "{{rag-backend-rate-limit-calls}}"
    assert limit.get("renewal-period") == "{{rag-backend-rate-limit-period-seconds}}"
    # One shared counter, so cached and uncached traffic protect the same backend.
    assert limit.get("counter-key") == '@("rag-backend:" + context.Api.Id)'


def test_rate_limit_follows_the_cache_lookup():
    """Microsoft's caching guidance: throttle immediately after the lookup so an
    unavailable cache cannot overload the backend."""
    inbound = section(parse(BUILT_IN_POLICY), "inbound")
    order = [child.tag for child in inbound]
    lookup_index = next(
        index
        for index, child in enumerate(inbound)
        if child.tag == "choose" and child.find(".//cache-lookup-value") is not None
    )
    assert order.index("rate-limit-by-key") > lookup_index


def test_backend_request_has_a_bounded_timeout():
    backend = section(parse(API_POLICY), "backend")
    forward = backend.find("forward-request")
    assert forward is not None
    assert forward.get("timeout") == "{{rag-backend-timeout-seconds}}"


def test_error_path_reports_a_cache_fallback_never_a_hit():
    on_error = section(parse(API_POLICY), "on-error")
    headers = set_headers(on_error)
    assert "ERROR-FALLBACK" in headers["x-demo-cache"]
    assert "HIT" not in headers["x-demo-cache"]


# ── Visible proof (spec: "Gateway cache outcome") ────────────────────────


def test_outbound_sets_every_proof_header():
    outbound = section(parse(API_POLICY), "outbound")
    headers = set_headers(outbound)
    for name in PROOF_RESPONSE_HEADERS:
        assert name in headers, f"missing proof header {name}"
    assert headers["x-demo-generation"] == "{{rag-knowledge-generation}}"


def test_built_in_operation_reports_store_outcome_and_ttl():
    outbound = section(parse(BUILT_IN_POLICY), "outbound")
    headers = set_headers(outbound)
    assert headers.get("x-demo-cache-ttl-seconds") == "{{rag-cache-ttl-seconds}}"
    assert "x-demo-cache-store" in headers


def test_baseline_marks_storage_as_not_applicable():
    outbound = section(parse(BASELINE_POLICY), "outbound")
    assert set_headers(outbound).get("x-demo-cache-store") == "not-applicable"


# ── Privacy (spec: "Cache identifier inspection") ────────────────────────


@pytest.mark.parametrize("path", ALL_POLICIES)
def test_no_header_exposes_raw_question_or_full_cache_key(path):
    root = parse(path)
    for name, value in set_headers(root).items():
        for sensitive in ("questionRaw", "requestBodyText", "cachedBody", "responseBodyText"):
            assert sensitive not in value, f"{path}: header {name} would expose {sensitive}"
        # `cacheKeyId` is the opaque short digest and is allowed; `cacheKey` is not.
        assert not re.search(r'"cacheKey"', value), f"{path}: header {name} exposes the full cache key"


@pytest.mark.parametrize("path", ALL_POLICIES)
def test_policies_contain_no_inline_secrets(path):
    text = read(path).lower()
    for forbidden in ("accountkey=", "sharedaccesskey", "instrumentationkey=", "password="):
        assert forbidden not in text
