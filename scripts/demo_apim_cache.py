#!/usr/bin/env python
"""demo_apim_cache.py — repeatable presenter driver for the APIM exact-cache
demo (openspec: add-apim-exact-cache-demo, task 6.3).

Drives `POST /rag/baseline` and `POST /rag/apim-built-in` through the deployed
APIM gateway and prints, for every call: elapsed wall-clock time, the gateway's
cache/proof headers, the answer's citations, and backend/cached invocation
metadata — everything `docs/APIM-EXACT-CACHE-DEMO.md`'s presenter sequence
needs, without ever printing the APIM subscription key.

This is a *gateway* client: unlike `scripts/demo.py` (which calls Azure AI
Search / Azure OpenAI directly for the ingestion demo), it only speaks HTTP to
the deployed `/rag/*` operations, so it measures exactly what a real caller —
and the presenter — would see.

Usage:
  # Subscription key resolved once via the APIM listSecrets ARM action, never
  # printed. Requires an authenticated `az login` session with Reader access
  # on the APIM instance.
  .venv/bin/python scripts/demo_apim_cache.py \
      --gateway-url https://docintv2-dev-apim.azure-api.net \
      --resource-group docintv2-dev-rg --apim-name docintv2-dev-apim \
      "What does the warranty cover?"

  # Or supply the key out-of-band via an environment variable (still never
  # printed) if apimSubscriptionRequired=true and you already have it:
  RAG_APIM_SUBSCRIPTION_KEY=... .venv/bin/python scripts/demo_apim_cache.py \
      --gateway-url https://docintv2-dev-apim.azure-api.net "question"

  # apimSubscriptionRequired=false deployments need neither:
  .venv/bin/python scripts/demo_apim_cache.py \
      --gateway-url https://docintv2-dev-apim.azure-api.net --no-subscription-key "question"

Repeatable: every run performs the same fixed sequence (baseline x2, then
built-in-cache x2) so it can be re-run during a live demo, or after a
generation publication, to reproduce the same evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

BASELINE_PATH = "/rag/baseline"
BUILT_IN_PATH = "/rag/apim-built-in"

# Response headers this driver reports. Never includes the subscription key —
# that header is only ever sent, never read back or logged.
PROOF_HEADERS = [
    "x-demo-cache",
    "x-demo-cache-type",
    "x-demo-cache-eligible",
    "x-demo-cache-store",
    "x-demo-cache-key-id",
    "x-demo-generation",
    "x-demo-security-scope",
    "x-demo-prompt-version",
    "x-demo-model-version",
    "x-demo-correlation-id",
    "x-demo-backend-invocation-id",
    "x-demo-cached-backend-invocation-id",
    "x-demo-cached-at",
    "server-timing",
]

BOLD, DIM, GREEN, CYAN, YELLOW, RED, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[36m", "\033[33m", "\033[31m", "\033[0m",
)


@dataclass
class CallResult:
    label: str
    url: str
    status_code: int
    elapsed_ms: float
    headers: dict = field(default_factory=dict)
    body: Optional[dict] = None
    error: Optional[str] = None


def _resolve_subscription_key(resource_group: str, apim_name: str, subscription_name: str) -> str:
    """Read the APIM subscription key via the caller's own `az login` session.

    Used once to build a request header and never printed, logged, or written
    to a file — matching `scripts/publish_generation.sh`'s handling of the
    same secret.
    """
    try:
        account = subprocess.run(
            ["az", "account", "show", "--query", "id", "-o", "tsv"],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        subscription_id = account.stdout.strip()
        if not subscription_id:
            raise SystemExit("ERROR: `az account show` returned an empty subscription ID.")
        url = (
            "https://management.azure.com/subscriptions/"
            f"{subscription_id}/resourceGroups/{resource_group}/providers/"
            "Microsoft.ApiManagement/service/"
            f"{apim_name}/subscriptions/{subscription_name}/listSecrets"
            "?api-version=2024-05-01"
        )
        result = subprocess.run(
            [
                "az", "rest",
                "--method", "post",
                "--url", url,
                "--query", "primaryKey",
                "-o", "tsv",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise SystemExit(
            "ERROR: could not read the APIM subscription key via the listSecrets ARM "
            f"action ({exc}). Pass --subscription-key-env with a pre-populated environment "
            "variable, or --no-subscription-key if apimSubscriptionRequired=false."
        ) from exc
    key = result.stdout.strip()
    if not key:
        raise SystemExit(
            "ERROR: the APIM listSecrets action returned an empty key. "
            "Confirm --resource-group/--apim-name/--subscription-name are correct."
        )
    return key


def _call(
    session: requests.Session,
    *,
    label: str,
    gateway_url: str,
    path: str,
    question: str,
    subscription_key: Optional[str],
    timeout_seconds: float,
) -> CallResult:
    url = f"{gateway_url.rstrip('/')}{path}"
    headers = {"Content-Type": "application/json"}
    if subscription_key:
        headers["Ocp-Apim-Subscription-Key"] = subscription_key

    start = time.perf_counter()
    try:
        response = session.post(
            url, json={"question": question}, headers=headers, timeout=timeout_seconds
        )
    except requests.RequestException as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return CallResult(label=label, url=url, status_code=0, elapsed_ms=elapsed_ms, error=str(exc))
    elapsed_ms = (time.perf_counter() - start) * 1000

    reported_headers = {
        name: response.headers[name] for name in PROOF_HEADERS if name in response.headers
    }
    try:
        body = response.json()
    except ValueError:
        body = None

    return CallResult(
        label=label,
        url=url,
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
        headers=reported_headers,
        body=body,
    )


def _print_result(result: CallResult) -> None:
    status_color = GREEN if 200 <= result.status_code < 300 else RED
    print(f"\n{BOLD}{CYAN}--- {result.label} ---{RESET}")
    print(f"  URL          : {result.url}")
    if result.error:
        print(f"  {RED}ERROR        : {result.error}{RESET}")
        return
    print(f"  Status       : {status_color}{result.status_code}{RESET}")
    print(f"  Elapsed      : {YELLOW}{result.elapsed_ms:.1f} ms{RESET}")

    if result.headers:
        print(f"  {DIM}Proof headers:{RESET}")
        for name, value in result.headers.items():
            print(f"    {name}: {value}")
    else:
        print(f"  {DIM}(no proof headers present){RESET}")

    if isinstance(result.body, dict):
        if "answer" in result.body:
            answer = str(result.body.get("answer", ""))
            preview = answer if len(answer) <= 200 else answer[:200] + "…"
            print(f"  Answer       : {preview}")
            citations = result.body.get("citations") or []
            if citations:
                print(f"  {DIM}Citations:{RESET}")
                for citation in citations:
                    source = citation.get("sourceFile", "?")
                    page = citation.get("page", "?")
                    ctype = citation.get("type", "?")
                    print(f"    - {source} (page {page}, {ctype})")
            execution = result.body.get("execution") or {}
            if execution:
                print(f"  {DIM}Backend execution metadata (body):{RESET}")
                print(
                    "    backendInvocationId="
                    f"{execution.get('backendInvocationId')} "
                    f"embeddingCalled={execution.get('embeddingCalled')} "
                    f"searchCalled={execution.get('searchCalled')} "
                    f"modelCalled={execution.get('modelCalled')} "
                    f"inputTokens={execution.get('inputTokens')} "
                    f"outputTokens={execution.get('outputTokens')}"
                )
        elif "error" in result.body:
            print(f"  {RED}Error body   : {result.body.get('error')} — {result.body.get('message')}{RESET}")


def run_sequence(
    *,
    gateway_url: str,
    question: str,
    subscription_key: Optional[str],
    baseline_repeats: int,
    timeout_seconds: float,
) -> list[CallResult]:
    """The fixed, repeatable demonstration sequence (task 6.3):

      1. `/rag/baseline` called `baseline_repeats` times — every call should
         invoke the backend and get a distinct backend invocation ID
         (spec: "Repeated baseline request").
      2. `/rag/apim-built-in` called twice with the same question — the first
         is expected to miss, the second to hit within the configured TTL
         (spec: "First/Repeated built-in-cache request").
    """
    results: list[CallResult] = []
    with requests.Session() as session:
        for i in range(1, baseline_repeats + 1):
            results.append(
                _call(
                    session,
                    label=f"baseline #{i} (uncached — expect a new backend invocation every time)",
                    gateway_url=gateway_url,
                    path=BASELINE_PATH,
                    question=question,
                    subscription_key=subscription_key,
                    timeout_seconds=timeout_seconds,
                )
            )

        results.append(
            _call(
                session,
                label="built-in-cache #1 (expect MISS — first time for this question/generation)",
                gateway_url=gateway_url,
                path=BUILT_IN_PATH,
                question=question,
                subscription_key=subscription_key,
                timeout_seconds=timeout_seconds,
            )
        )
        results.append(
            _call(
                session,
                label="built-in-cache #2 (expect HIT — repeated within TTL)",
                gateway_url=gateway_url,
                path=BUILT_IN_PATH,
                question=question,
                subscription_key=subscription_key,
                timeout_seconds=timeout_seconds,
            )
        )
    return results


def _print_summary(results: list[CallResult]) -> None:
    print(f"\n{BOLD}{CYAN}=== Summary ==={RESET}")
    print(f"  {'label':<70} {'status':>6} {'elapsed_ms':>10} {'cache':>6}")
    for result in results:
        cache_outcome = result.headers.get("x-demo-cache", "-")
        print(f"  {result.label:<70} {result.status_code:>6} {result.elapsed_ms:>10.1f} {cache_outcome:>6}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="Question to submit to both demo operations")
    parser.add_argument("--gateway-url", required=True, help="APIM gateway URL, e.g. https://<apim>.azure-api.net")
    parser.add_argument("--resource-group", help="Resource group containing the APIM instance (for subscription-key lookup)")
    parser.add_argument("--apim-name", help="APIM service name (for subscription-key lookup)")
    parser.add_argument("--subscription-name", default="rag-demo", help="APIM subscription name (default: rag-demo)")
    parser.add_argument(
        "--subscription-key-env",
        help="Name of an environment variable already holding the subscription key "
        "(skips the APIM listSecrets ARM lookup)",
    )
    parser.add_argument(
        "--no-subscription-key",
        action="store_true",
        help="Do not send a subscription key (apimSubscriptionRequired=false deployments)",
    )
    parser.add_argument("--baseline-repeats", type=int, default=2, help="Number of /rag/baseline calls (default: 2)")
    parser.add_argument("--timeout-seconds", type=float, default=60.0, help="Per-request HTTP timeout (default: 60)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of the formatted report")
    args = parser.parse_args(argv)

    subscription_key: Optional[str] = None
    if not args.no_subscription_key:
        if args.subscription_key_env:
            import os

            subscription_key = os.environ.get(args.subscription_key_env)
            if not subscription_key:
                print(
                    f"ERROR: environment variable {args.subscription_key_env!r} is not set or empty",
                    file=sys.stderr,
                )
                return 1
        elif args.resource_group and args.apim_name:
            subscription_key = _resolve_subscription_key(args.resource_group, args.apim_name, args.subscription_name)
        else:
            print(
                "ERROR: provide --resource-group/--apim-name (to resolve the subscription key "
                "via az cli), --subscription-key-env (to reuse an existing value), or "
                "--no-subscription-key (if the API requires none).",
                file=sys.stderr,
            )
            return 1

    results = run_sequence(
        gateway_url=args.gateway_url,
        question=args.question,
        subscription_key=subscription_key,
        baseline_repeats=max(1, args.baseline_repeats),
        timeout_seconds=args.timeout_seconds,
    )
    del subscription_key  # out of scope for the rest of main(); never logged above

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "label": r.label,
                        "url": r.url,
                        "statusCode": r.status_code,
                        "elapsedMs": r.elapsed_ms,
                        "headers": r.headers,
                        "error": r.error,
                    }
                    for r in results
                ],
                indent=2,
            )
        )
        return 0

    for result in results:
        _print_result(result)
    _print_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
