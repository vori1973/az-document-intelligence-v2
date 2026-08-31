"""
Fixtures and skip logic for Azure integration tests against a *deployed*
APIM exact-cache demo (openspec: add-apim-exact-cache-demo, task 6.4/6.5).

Nothing here runs by default. Every test in `tests/integration/` requires
`RAG_INTEGRATION_TESTS=1` plus the specific environment variables its
scenario needs; anything missing is a `pytest.skip`, never a failure, so the
ordinary unit suite (and CI without live Azure resources) stays green.

These tests exercise a real, already-deployed environment. They never
provision, delete, or reconfigure infrastructure — the only mutation any test
performs is a temporary APIM named-value change that is restored in a
`finally` block, and only when an additional opt-in variable is set.

Environment variables:
  RAG_INTEGRATION_TESTS=1        Master opt-in. Required for every test below.
  RAG_APIM_GATEWAY_URL            Required. e.g. https://<apim>.azure-api.net
  RAG_APIM_SUBSCRIPTION_KEY       Optional. Omit only if the deployment has
                                  apimSubscriptionRequired=false AND
                                  RAG_APIM_NO_SUBSCRIPTION_KEY=1 is also set.
  RAG_APIM_NO_SUBSCRIPTION_KEY=1  Explicit acknowledgement that no key is sent.
  RAG_QUERY_BACKEND_URL           Optional. Base query backend URL including
                                  the /api route prefix (bicep output
                                  `queryBackendUrl`). Required only for the
                                  direct-backend-rejection scenario.
  RAG_APIM_RESOURCE_GROUP,
  RAG_APIM_NAME                   Optional. Required only for the trusted
                                  cache-dimension / generation-change
                                  scenarios (they call `az apim nv update`).
  RAG_ALLOW_NAMED_VALUE_MUTATION=1
                                  Required in addition to the two above:
                                  a second, explicit acknowledgement that the
                                  test may temporarily mutate a shared APIM
                                  named value (restored afterward).
  RAG_TELEMETRY_TESTS=1,
  RAG_APPINSIGHTS_APP_ID           Optional. Required only for the telemetry
                                  evidence scenario, which polls Application
                                  Insights and is slow / best-effort because
                                  telemetry ingestion is eventually consistent.
  RAG_INTEGRATION_TIMEOUT_SECONDS  Optional. Per-request HTTP timeout
                                  (default: 60).
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from collections.abc import Callable
from typing import Optional

import pytest
import requests

INTEGRATION_ENABLED = os.environ.get("RAG_INTEGRATION_TESTS") == "1"
GATEWAY_URL = os.environ.get("RAG_APIM_GATEWAY_URL", "").rstrip("/")
SUBSCRIPTION_KEY = os.environ.get("RAG_APIM_SUBSCRIPTION_KEY", "")
NO_SUBSCRIPTION_KEY = os.environ.get("RAG_APIM_NO_SUBSCRIPTION_KEY") == "1"
QUERY_BACKEND_URL = os.environ.get("RAG_QUERY_BACKEND_URL", "").rstrip("/")
APIM_RESOURCE_GROUP = os.environ.get("RAG_APIM_RESOURCE_GROUP", "")
APIM_NAME = os.environ.get("RAG_APIM_NAME", "")
ALLOW_NAMED_VALUE_MUTATION = os.environ.get("RAG_ALLOW_NAMED_VALUE_MUTATION") == "1"
TELEMETRY_TESTS = os.environ.get("RAG_TELEMETRY_TESTS") == "1"
APPINSIGHTS_APP_ID = os.environ.get("RAG_APPINSIGHTS_APP_ID", "")
TIMEOUT_SECONDS = float(os.environ.get("RAG_INTEGRATION_TIMEOUT_SECONDS", "60"))
EVENTUAL_CONSISTENCY_SECONDS = float(os.environ.get("RAG_EVENTUAL_CONSISTENCY_SECONDS", "90"))

requires_gateway = pytest.mark.skipif(
    not INTEGRATION_ENABLED or not GATEWAY_URL,
    reason="set RAG_INTEGRATION_TESTS=1 and RAG_APIM_GATEWAY_URL to run against a deployed gateway",
)
requires_direct_backend = pytest.mark.skipif(
    not INTEGRATION_ENABLED or not QUERY_BACKEND_URL,
    reason="set RAG_INTEGRATION_TESTS=1 and RAG_QUERY_BACKEND_URL for the direct-backend-rejection scenario",
)
requires_named_value_mutation = pytest.mark.skipif(
    not INTEGRATION_ENABLED
    or not GATEWAY_URL
    or not APIM_RESOURCE_GROUP
    or not APIM_NAME
    or not ALLOW_NAMED_VALUE_MUTATION,
    reason=(
        "set RAG_INTEGRATION_TESTS=1, RAG_APIM_GATEWAY_URL, RAG_APIM_RESOURCE_GROUP, "
        "RAG_APIM_NAME, and RAG_ALLOW_NAMED_VALUE_MUTATION=1 to run scenarios that "
        "temporarily change a trusted APIM named value"
    ),
)
requires_telemetry = pytest.mark.skipif(
    not INTEGRATION_ENABLED or not TELEMETRY_TESTS or not APPINSIGHTS_APP_ID,
    reason="set RAG_INTEGRATION_TESTS=1, RAG_TELEMETRY_TESTS=1, and RAG_APPINSIGHTS_APP_ID for telemetry evidence checks",
)


def unique_question(label: str) -> str:
    """A question unlikely to collide with cache entries from a previous run
    or a concurrent test, so miss/hit assertions are not polluted by state
    left over from earlier executions of this same suite."""
    return f"Integration test probe {label} {uuid.uuid4().hex}"


@pytest.fixture(scope="session")
def http_session():
    with requests.Session() as session:
        yield session


def post_rag(
    session: requests.Session,
    path: str,
    *,
    question: Optional[str] = None,
    body: Optional[dict] = None,
    raw_body: Optional[str] = None,
) -> requests.Response:
    """POST to one of the deployed `/rag/*` operations.

    Never logs or returns the subscription key — it only ever appears as a
    request header value inside this process.
    """
    headers = {"Content-Type": "application/json"}
    if SUBSCRIPTION_KEY:
        headers["Ocp-Apim-Subscription-Key"] = SUBSCRIPTION_KEY
    elif not NO_SUBSCRIPTION_KEY:
        pytest.skip(
            "RAG_APIM_SUBSCRIPTION_KEY is not set; set it, or set "
            "RAG_APIM_NO_SUBSCRIPTION_KEY=1 if the deployment requires no subscription key"
        )

    if raw_body is not None:
        payload = raw_body.encode("utf-8")
    else:
        payload = None
        if body is None:
            body = {"question": question}

    return session.post(
        f"{GATEWAY_URL}{path}",
        data=payload,
        json=None if payload is not None else body,
        headers=headers,
        timeout=TIMEOUT_SECONDS,
    )


def read_named_value(named_value_id: str) -> str:
    result = subprocess.run(
        [
            "az", "apim", "nv", "show",
            "--resource-group", APIM_RESOURCE_GROUP,
            "--service-name", APIM_NAME,
            "--named-value-id", named_value_id,
            "--query", "value",
            "-o", "tsv",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return result.stdout.strip()


def write_named_value(named_value_id: str, value: str) -> None:
    subprocess.run(
        [
            "az", "apim", "nv", "update",
            "--resource-group", APIM_RESOURCE_GROUP,
            "--service-name", APIM_NAME,
            "--named-value-id", named_value_id,
            "--value", value,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )


def wait_for_response(
    request: Callable[[], requests.Response],
    predicate: Callable[[requests.Response], bool],
    *,
    description: str,
) -> requests.Response:
    deadline = time.monotonic() + EVENTUAL_CONSISTENCY_SECONDS
    last_response: Optional[requests.Response] = None
    while time.monotonic() < deadline:
        last_response = request()
        if predicate(last_response):
            return last_response
        time.sleep(3)

    detail = "no response received"
    if last_response is not None:
        detail = (
            f"status={last_response.status_code}, "
            f"cache={last_response.headers.get('x-demo-cache')}, "
            f"generation={last_response.headers.get('x-demo-generation')}, "
            f"promptVersion={last_response.headers.get('x-demo-prompt-version')}"
        )
    pytest.fail(f"timed out waiting for {description}: {detail}")
