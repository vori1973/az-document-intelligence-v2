"""
Automated Azure integration tests for the deployed APIM exact-cache demo
(openspec: add-apim-exact-cache-demo, tasks 6.4 / 6.5).

Every test is skipped unless its required environment variables are set (see
`conftest.py`) — this module makes zero live Azure calls, mutates zero
infrastructure, and adds zero time to `pytest tests/` in its default
configuration. Enabling it requires a real deployed gateway (and, for two
scenarios, explicit extra opt-in because they temporarily mutate a shared APIM
named value or poll Application Insights).

Each test references the spec scenario it validates from
`openspec/changes/add-apim-exact-cache-demo/specs/apim-exact-cache-demo/spec.md`.
"""

from __future__ import annotations

import json
import subprocess
import time

import pytest

from .conftest import (
    APPINSIGHTS_APP_ID,
    QUERY_BACKEND_URL,
    TIMEOUT_SECONDS,
    post_rag,
    read_named_value,
    requires_direct_backend,
    requires_gateway,
    requires_named_value_mutation,
    requires_telemetry,
    unique_question,
    wait_for_response,
    write_named_value,
)

BASELINE = "/rag/baseline"
BUILT_IN = "/rag/apim-built-in"


# ── Repeated baseline (spec: "Repeated baseline request") ──────────────────


@requires_gateway
def test_repeated_baseline_request_invokes_backend_each_time(http_session):
    question = unique_question("baseline-repeat")

    first = post_rag(http_session, BASELINE, question=question)
    second = post_rag(http_session, BASELINE, question=question)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    first_id = first.headers.get("x-demo-backend-invocation-id")
    second_id = second.headers.get("x-demo-backend-invocation-id")
    assert first_id and second_id, "baseline responses must carry a backend invocation id"
    assert first_id != second_id, "two baseline calls must invoke the backend twice, not share an invocation"
    assert first.headers.get("x-demo-cache", "").upper() == "BYPASS"
    assert second.headers.get("x-demo-cache", "").upper() == "BYPASS"


# ── Built-in cache miss then hit (spec: "First/Repeated built-in-cache request") ──


@requires_gateway
def test_built_in_cache_first_miss_then_repeated_hit(http_session):
    question = unique_question("built-in-miss-hit")

    miss = post_rag(http_session, BUILT_IN, question=question)
    assert miss.status_code == 200, miss.text
    assert miss.headers.get("x-demo-cache", "").upper() == "MISS"
    miss_backend_id = miss.headers.get("x-demo-backend-invocation-id")
    assert miss_backend_id, "a cache miss must report a backend invocation id"

    hit = post_rag(http_session, BUILT_IN, question=question)
    assert hit.status_code == 200, hit.text
    assert hit.headers.get("x-demo-cache", "").upper() == "HIT"
    # A hit must not report a *new* backend invocation id (spec: "no new backend
    # invocation ... recorded for that request"); the cached one is reported
    # separately for reference.
    assert not hit.headers.get("x-demo-backend-invocation-id")
    assert hit.headers.get("x-demo-cached-backend-invocation-id") == miss_backend_id
    assert hit.headers.get("x-demo-cache-key-id") == miss.headers.get("x-demo-cache-key-id")


# ── Normalization equivalence (spec: "Equivalent normalized question") ─────


@requires_gateway
def test_normalization_equivalence_resolves_same_cache_identity(http_session):
    base_question = unique_question("normalization")
    # Extra internal whitespace and case differences only — the documented
    # contract (trim, collapse whitespace, lowercase) must still resolve to
    # the same identity as the base question.
    variant_question = f"   {base_question.upper()}   ".replace(" ", "  ")

    prime = post_rag(http_session, BUILT_IN, question=base_question)
    assert prime.status_code == 200, prime.text
    assert prime.headers.get("x-demo-cache", "").upper() == "MISS"

    variant = post_rag(http_session, BUILT_IN, question=variant_question)
    assert variant.status_code == 200, variant.text
    assert variant.headers.get("x-demo-cache", "").upper() == "HIT", (
        "a whitespace/case-only variant of an already-cached question must be a hit"
    )
    assert variant.headers.get("x-demo-cache-key-id") == prime.headers.get("x-demo-cache-key-id")


# ── Changed trusted cache dimension via generation (spec: "Material cache
#    dimension changes" / "Request after generation publication") ─────────


@requires_named_value_mutation
def test_generation_change_produces_cache_miss(http_session):
    """Bumping the trusted `knowledgeGeneration` dimension must make a
    previously cached question a miss again, without a bulk cache purge
    (spec: "Request after generation publication")."""
    question = unique_question("generation-change")
    original_generation = read_named_value("rag-knowledge-generation")
    temporary_generation = f"{original_generation}-it-{int(time.time())}"

    prime = post_rag(http_session, BUILT_IN, question=question)
    assert prime.status_code == 200, prime.text
    assert prime.headers.get("x-demo-cache", "").upper() == "MISS"

    wait_for_response(
        lambda: post_rag(http_session, BUILT_IN, question=question),
        lambda response: response.headers.get("x-demo-cache", "").upper() == "HIT",
        description="the primed response to become a cache hit",
    )

    try:
        write_named_value("rag-knowledge-generation", temporary_generation)
        after_change = wait_for_response(
            lambda: post_rag(http_session, BUILT_IN, question=question),
            lambda response: (
                response.headers.get("x-demo-generation") == temporary_generation
                and response.headers.get("x-demo-cache", "").upper() == "MISS"
            ),
            description="the new knowledge generation to reach the gateway",
        )
        assert after_change.status_code == 200, after_change.text
        assert after_change.headers.get("x-demo-generation") == temporary_generation
    finally:
        write_named_value("rag-knowledge-generation", original_generation)
        wait_for_response(
            lambda: post_rag(http_session, BASELINE, question=unique_question("generation-restore")),
            lambda response: response.headers.get("x-demo-generation") == original_generation,
            description="the original knowledge generation to be restored",
        )


@requires_named_value_mutation
def test_other_trusted_dimension_change_produces_cache_miss(http_session):
    """A change to any trusted cache dimension — not just generation — must
    resolve to a different cache identity (spec: "Material cache dimension
    changes"). Exercised here via `promptVersion`, which is safe to restore
    afterward like generation."""
    question = unique_question("prompt-version-change")
    original_prompt_version = read_named_value("rag-prompt-version")
    temporary_prompt_version = f"{original_prompt_version}-it-{int(time.time())}"

    prime = post_rag(http_session, BUILT_IN, question=question)
    assert prime.status_code == 200, prime.text
    assert prime.headers.get("x-demo-cache", "").upper() == "MISS"

    try:
        write_named_value("rag-prompt-version", temporary_prompt_version)
        after_change = wait_for_response(
            lambda: post_rag(http_session, BUILT_IN, question=question),
            lambda response: (
                response.headers.get("x-demo-prompt-version") == temporary_prompt_version
                and response.headers.get("x-demo-cache", "").upper() == "MISS"
            ),
            description="the new prompt version to reach the gateway",
        )
        assert after_change.status_code == 200, after_change.text
        assert after_change.headers.get("x-demo-prompt-version") == temporary_prompt_version
        assert after_change.headers.get("x-demo-cache-key-id") != prime.headers.get("x-demo-cache-key-id")
    finally:
        write_named_value("rag-prompt-version", original_prompt_version)
        wait_for_response(
            lambda: post_rag(http_session, BASELINE, question=unique_question("prompt-restore")),
            lambda response: response.headers.get("x-demo-prompt-version") == original_prompt_version,
            description="the original prompt version to be restored",
        )


# ── Uncached errors (spec: "Invalid query request" / "Backend error response") ──


@requires_gateway
def test_uncached_error_responses_are_never_stored(http_session):
    # Missing question entirely — rejected by the API-scope policy before any
    # backend invocation or cache write is possible.
    missing_question = post_rag(http_session, BUILT_IN, body={})
    assert missing_question.status_code == 400, missing_question.text
    assert missing_question.headers.get("x-demo-cache-eligible", "").lower() != "true"

    # Repeating the identical malformed request must still be rejected — if it
    # had ever been cached, this would incorrectly return a stored 200.
    repeat = post_rag(http_session, BUILT_IN, body={})
    assert repeat.status_code == 400, repeat.text
    assert repeat.headers.get("x-demo-cache", "").upper() != "HIT"


# ── Direct backend rejection (spec: "Direct backend access attempt") ──────


@requires_direct_backend
def test_direct_backend_access_is_rejected(http_session):
    """A caller without the APIM gateway's managed-identity token must not
    reach the query backend directly."""
    response = http_session.post(
        f"{QUERY_BACKEND_URL}/internal/query",
        json={"question": unique_question("direct-backend")},
        timeout=TIMEOUT_SECONDS,
    )
    assert response.status_code in (401, 403), (
        f"expected the unauthenticated-through-APIM backend to reject a direct caller, got {response.status_code}"
    )


# ── Telemetry evidence (spec: "Correlated privacy-preserving telemetry") ──


@requires_telemetry
def test_telemetry_evidence_distinguishes_cache_outcomes(http_session):
    """Prove gateway outcomes and downstream work for baseline, miss, and hit.

    APIM emits the same response cache-outcome header for every path, including
    ERROR-FALLBACK when a cache policy fails. The live assertions exercise the
    normally reachable outcomes and prove the hit has no query request,
    dependency, or token-bearing success event.
    """
    baseline = post_rag(http_session, BASELINE, question=unique_question("telemetry-baseline"))
    assert baseline.status_code == 200, baseline.text

    question = unique_question("telemetry-cache")
    miss = post_rag(http_session, BUILT_IN, question=question)
    assert miss.status_code == 200, miss.text
    hit = wait_for_response(
        lambda: post_rag(http_session, BUILT_IN, question=question),
        lambda response: response.headers.get("x-demo-cache", "").upper() == "HIT",
        description="the telemetry probe to become a cache hit",
    )

    correlations = {
        "BYPASS": baseline.headers.get("x-demo-correlation-id"),
        "MISS": miss.headers.get("x-demo-correlation-id"),
        "HIT": hit.headers.get("x-demo-correlation-id"),
    }
    assert all(correlations.values()), "every response must carry a correlation id"

    correlation_literals = ", ".join(f"'{value}'" for value in correlations.values())
    gateway_query = (
        "requests "
        "| where timestamp > ago(30m) and cloud_RoleName startswith 'docintv2-dev-apim' "
        "| extend correlationId=tostring(customDimensions['Response-x-demo-correlation-id']), "
        "cacheOutcome=tostring(customDimensions['Response-x-demo-cache']) "
        f"| where correlationId in ({correlation_literals}) "
        "| project correlationId, cacheOutcome, operation_Id"
    )

    deadline = time.monotonic() + 180
    gateway_rows: list[list[str]] = []
    last_error = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "az", "monitor", "app-insights", "query",
                "--app", APPINSIGHTS_APP_ID,
                "--analytics-query", gateway_query,
                "-o", "json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            gateway_rows = payload["tables"][0]["rows"]
            if len(gateway_rows) == 3:
                break
        else:
            last_error = result.stderr
        time.sleep(15)

    assert len(gateway_rows) == 3, (
        "expected correlated APIM request rows for baseline, miss, and hit within 180s "
        f"(last az error: {last_error})"
    )

    observed = {row[0]: (row[1], row[2]) for row in gateway_rows}
    for expected_outcome, correlation_id in correlations.items():
        assert observed[correlation_id][0].upper() == expected_outcome

    operation_ids = {outcome: observed[correlation_id][1] for outcome, correlation_id in correlations.items()}
    operation_filter = " or ".join(
        f"operation_Id == '{operation_id}'" for operation_id in operation_ids.values()
    )
    work_queries = {
        "query-request": (
            "requests | where timestamp > ago(30m) "
            f"| where name == 'query' and ({operation_filter}) "
            "| project operation_Id, name"
        ),
        "dependency": (
            "dependencies | where timestamp > ago(30m) "
            f"| where cloud_RoleName == 'docintv2-dev-query-func' and ({operation_filter}) "
            "| project operation_Id, name"
        ),
        "query-success": (
            "traces | where timestamp > ago(30m) "
            "| where message == 'rag.query.success' "
            "| where isnotempty(tostring(customDimensions.input_tokens)) "
            f"and ({operation_filter}) "
            "| project operation_Id, "
            "name=strcat(tostring(customDimensions.input_tokens), ':', "
            "tostring(customDimensions.output_tokens))"
        ),
    }
    work_rows: list[list[str]] = []
    for kind, query in work_queries.items():
        work_result = subprocess.run(
            [
                "az", "monitor", "app-insights", "query",
                "--app", APPINSIGHTS_APP_ID,
                "--analytics-query", query,
                "-o", "json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        work_rows.extend(
            [row[0], kind, row[1]]
            for row in json.loads(work_result.stdout)["tables"][0]["rows"]
        )
    rows_by_operation = {
        operation_id: [row for row in work_rows if row[0] == operation_id]
        for operation_id in operation_ids.values()
    }

    for outcome in ("BYPASS", "MISS"):
        rows = rows_by_operation[operation_ids[outcome]]
        assert any(row[1] == "query-request" for row in rows)
        assert any(row[1] == "dependency" and "search" in row[2].lower() for row in rows)
        success_rows = [row for row in rows if row[1] == "query-success"]
        assert success_rows and all(part for part in success_rows[0][2].split(":"))

    assert rows_by_operation[operation_ids["HIT"]] == [], (
        "a cache hit must produce no query-backend request, Search/model dependency, "
        "or token-bearing query success event"
    )
