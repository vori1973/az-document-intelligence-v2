#!/usr/bin/env python3
"""
load_test.py — Async concurrent load runner for Azure AI Search.

Usage:
    python load_test.py --concurrency 10 --duration 60 --profile hybrid --replicas 1

Environment variables required:
    AZURE_SEARCH_ENDPOINT   https://<name>.search.windows.net
    AZURE_SEARCH_INDEX      document-chunks (or your index name)

Optional (for semantic profile):
    AZURE_SEARCH_SEMANTIC_CONFIG   semantic-config (defaults to "semantic-config")

Workflow — before/after semantic ranker comparison:
    1. Run hybrid profile first (works without semantic ranker):
       python load_test.py --concurrency 10 --duration 60 --profile hybrid --replicas 1

    2. Enable semantic ranker on the service (one-time, no reindex needed):
       az search service update --name <svc> --resource-group <rg> --semantic-search free

    3. Run semantic profile:
       python load_test.py --concurrency 10 --duration 60 --profile semantic --replicas 1

    4. Compare in advisor:
       python advisor.py results/

query_bank.json must exist in the same directory (run embed_queries.py first).
"""

import argparse
import asyncio
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizedQuery

SCRIPT_DIR = Path(__file__).parent
QUERY_BANK_FILE = SCRIPT_DIR / "query_bank.json"
RESULTS_DIR = SCRIPT_DIR / "results"

PROFILES = ("vector", "hybrid", "semantic")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Azure AI Search async load tester",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--concurrency", type=int, default=10,
                        help="Number of parallel async workers")
    parser.add_argument("--duration", type=int, default=60,
                        help="Test duration in seconds")
    parser.add_argument("--profile", choices=PROFILES, default="hybrid",
                        help="Query profile: vector, hybrid, or semantic")
    parser.add_argument("--replicas", type=int, default=1,
                        help="Replica count label (metadata only — does not change the service)")
    parser.add_argument("--log-requests", action="store_true",
                        help="Write per-request detail (query, scores, result snippets) to a JSONL file alongside the results JSON. Useful for inspecting semantic ranker output.")
    parser.add_argument("--no-perturb", action="store_true",
                        help="Disable vector perturbation. By default a tiny noise (~0.001) is added to each query vector to bust Azure Search's query cache and produce realistic load.")
    parser.add_argument("--retry-total", type=int, default=3,
                        help="SDK retry attempts on transient errors (503). Set to 0 to disable retries and surface 503s as real errors in results.")
    parser.add_argument("--expensive", action="store_true",
                        help="Simulate large-index query cost: raises k_nearest_neighbors to 500 and top to 50. "
                             "Forces deep HNSW graph traversal so each query consumes ~10-100x more CPU, "
                             "reproducing 429 throttling without needing a 16GB index.")
    parser.add_argument("--k", type=int, default=None,
                        help="Override k_nearest_neighbors (HNSW traversal depth). "
                             "LangChain default is 4; production RAG setups often use 50–100. "
                             "Higher k = deeper graph traversal = more CPU per query. "
                             "Ignored when --expensive is set (which forces k=500).")
    parser.add_argument("--top", type=int, default=None,
                        help="Override the number of results returned (top N). "
                             "Defaults to match --k when set, otherwise 5. "
                             "Ignored when --expensive is set (which forces top=50).")
    parser.add_argument("--oversampling", type=int, default=None,
                        help="Multiply k_nearest_neighbors internally before applying filters. "
                             "Azure Search fetches k × oversampling HNSW candidates, then "
                             "filters/reranks down to k results. "
                             "Customer default is 20 (k=50 → 1,000 internal candidates). "
                             "Omit to use the service default (no oversampling).")
    return parser.parse_args()


def load_query_bank() -> list[dict]:
    if not QUERY_BANK_FILE.exists():
        sys.exit(
            f"ERROR: {QUERY_BANK_FILE} not found.\n"
            "Run embed_queries.py first to generate the query bank."
        )
    bank = json.loads(QUERY_BANK_FILE.read_text(encoding="utf-8"))
    if not bank:
        sys.exit("ERROR: query_bank.json is empty.")
    return bank


def perturb_vector(vector: list[float], magnitude: float = 0.001) -> list[float]:
    """
    Add tiny Gaussian noise to a query vector before each request.
    Busts Azure Search's exact-match query cache without meaningfully
    changing the search results (noise norm ~0.039 vs unit signal norm 1.0).
    """
    return [v + random.gauss(0, magnitude) for v in vector]


def _extract_result_doc(r: dict, profile: str) -> dict:
    """Extract loggable fields from one search result document."""
    captions = r.get("@search.captions") or []
    return {
        "score": r.get("@search.score"),
        "reranker_score": r.get("@search.rerankerScore"),  # None for non-semantic
        "source_file": r.get("source_file"),
        "text_snippet": (r.get("text_for_embedding") or "")[:400],
        "captions": [
            {"text": c.get("text"), "highlights": c.get("highlights")}
            for c in (captions if isinstance(captions, list) else [])
        ],
    }


async def build_search_request(
    client: SearchClient,
    query: dict,
    profile: str,
    semantic_config: str,
    capture: bool = False,
    perturb: bool = True,
    expensive: bool = False,
    k: int = 5,
    top: int = 5,
    oversampling: int | None = None,
) -> tuple[int, float, list | None]:
    """
    Issue one search request and return (http_status_code, latency_ms, docs).
    docs is a list of result dicts when capture=True, else None.
    Status 429 is counted but not raised.
    perturb=True adds tiny noise to the query vector to bust the search cache.
    expensive=True overrides k=500, top=50 to simulate large-index query cost.
    k controls k_nearest_neighbors (HNSW traversal depth); top controls result count.
    oversampling multiplies the internal candidate set (k × oversampling fetched from HNSW).
    """
    vector = perturb_vector(query["vector"]) if perturb else query["vector"]
    text = query["text"]
    if expensive:
        k = 500
        top = 50

    def _vq(**extra):
        return VectorizedQuery(
            vector=vector,
            k_nearest_neighbors=k,
            fields="embedding",
            oversampling=oversampling,
            **extra,
        )

    t0 = time.monotonic()
    try:
        if profile == "vector":
            results = await client.search(
                search_text=None,
                vector_queries=[_vq()],
                top=top,
            )
        elif profile == "hybrid":
            results = await client.search(
                search_text=text,
                vector_queries=[_vq()],
                top=top,
            )
        else:  # semantic
            results = await client.search(
                search_text=text,
                vector_queries=[_vq()],
                query_type="semantic",
                semantic_configuration_name=semantic_config,
                top=top,
            )

        docs = []
        async for r in results:
            if capture:
                docs.append(_extract_result_doc(r, profile))

        latency_ms = (time.monotonic() - t0) * 1000
        return 200, latency_ms, docs if capture else None

    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        status = getattr(exc, "status_code", None)
        if status in (429, 503):
            return status, latency_ms, None
        raise


async def preflight_semantic_check(
    client: SearchClient,
    query: dict,
    semantic_config: str,
    service_name: str,
) -> None:
    """
    Verify semantic ranker is available before starting the load test.
    Exits with a clear message and the az command to enable it if not.
    """
    try:
        results = await client.search(
            search_text=query["text"],
            vector_queries=[
                VectorizedQuery(
                    vector=query["vector"],
                    k_nearest_neighbors=1,
                    fields="embedding",
                )
            ],
            query_type="semantic",
            semantic_configuration_name=semantic_config,
            top=1,
        )
        async for _ in results:
            pass
    except HttpResponseError as exc:
        msg = str(exc).lower()
        if "semantic" in msg or exc.status_code in (400, 404):
            print(
                "\nERROR: Semantic ranker is not enabled on this Azure AI Search service.\n"
                "\nEnable it with (free tier, no reindex needed):\n"
                f"  az search service update \\\n"
                f"    --name {service_name} \\\n"
                f"    --resource-group <your-resource-group> \\\n"
                f"    --semantic-search free\n"
                "\nThen re-run this script.\n"
                "To compare before/after without semantic ranker, use --profile hybrid first.\n"
            )
            sys.exit(1)
        raise


async def run_worker(
    worker_id: int,
    client: SearchClient,
    query_bank: list[dict],
    profile: str,
    semantic_config: str,
    end_time: float,
    results_list: list,
    counters: dict,
    log_state: dict | None = None,
    perturb: bool = True,
    expensive: bool = False,
    k: int = 5,
    top: int = 5,
    oversampling: int | None = None,
) -> None:
    while time.monotonic() < end_time:
        query = random.choice(query_bank)
        capture = log_state is not None
        status, latency_ms, docs = await build_search_request(
            client, query, profile, semantic_config, capture=capture, perturb=perturb,
            expensive=expensive, k=k, top=top, oversampling=oversampling,
        )
        results_list.append((status, latency_ms))
        counters["total"] += 1
        if status == 429:
            counters["throttled"] += 1
        elif status == 503:
            counters["errors_503"] += 1

        if log_state is not None and docs is not None:
            async with log_state["lock"]:
                seq = log_state["seq"]
                log_state["seq"] += 1
                entry = json.dumps({
                    "seq": seq,
                    "query": query["text"],
                    "profile": profile,
                    "status": status,
                    "latency_ms": round(latency_ms, 1),
                    "result_count": len(docs),
                    "results": docs,
                }, ensure_ascii=False)
                log_state["fh"].write(entry + "\n")


def compute_percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = math.ceil(pct / 100 * len(sorted_values)) - 1
    return sorted_values[max(0, idx)]


def aggregate_results(raw: list[tuple[int, float]], duration_s: int) -> dict:
    total = len(raw)
    if total == 0:
        return {
            "total_requests": 0,
            "successful": 0,
            "throttled_429": 0,
            "throttle_pct": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "achieved_qps": 0.0,
        }

    successful = sum(1 for status, _ in raw if status == 200)
    throttled = sum(1 for status, _ in raw if status == 429)
    errors_503 = sum(1 for status, _ in raw if status == 503)
    throttle_pct = round(throttled / total * 100, 2)
    error_503_pct = round(errors_503 / total * 100, 2)
    achieved_qps = round(total / duration_s, 2)

    latencies = sorted(lat for _, lat in raw)
    p50 = round(compute_percentile(latencies, 50), 1)
    p95 = round(compute_percentile(latencies, 95), 1)
    p99 = round(compute_percentile(latencies, 99), 1)

    return {
        "total_requests": total,
        "successful": successful,
        "throttled_429": throttled,
        "throttle_pct": throttle_pct,
        "errors_503": errors_503,
        "error_503_pct": error_503_pct,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "achieved_qps": achieved_qps,
    }


def run_dir(started_at: datetime, args: argparse.Namespace) -> Path:
    ts = started_at.strftime("%Y-%m-%dT%H-%M")
    return RESULTS_DIR / f"{ts}_c{args.concurrency}_{args.profile}_r{args.replicas}"


def write_results(
    args: argparse.Namespace, stats: dict, started_at: datetime,
    k: int = 5, top: int = 5, oversampling: int | None = None,
) -> Path:
    out_dir = run_dir(started_at, args)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "summary.json"

    payload = {
        "concurrency": args.concurrency,
        "profile": args.profile,
        "replicas": args.replicas,
        "duration_s": args.duration,
        "k_nearest_neighbors": k,
        "top": top,
        **({"oversampling": oversampling} if oversampling is not None else {}),
        **stats,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_dir


async def run_load_test(args: argparse.Namespace) -> None:
    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    index = os.environ.get("AZURE_SEARCH_INDEX")
    semantic_config = os.environ.get("AZURE_SEARCH_SEMANTIC_CONFIG", "semantic-config")

    if not endpoint:
        sys.exit("ERROR: AZURE_SEARCH_ENDPOINT environment variable is not set.")
    if not index:
        sys.exit("ERROR: AZURE_SEARCH_INDEX environment variable is not set.")

    query_bank = load_query_bank()
    api_key = os.environ.get("AZURE_SEARCH_API_KEY")
    credential = AzureKeyCredential(api_key) if api_key else DefaultAzureCredential()
    auth_method = "API key" if api_key else "DefaultAzureCredential"

    print(f"Azure AI Search Load Test")
    print(f"  Endpoint:    {endpoint}")
    print(f"  Auth:        {auth_method}")
    print(f"  Index:       {index}")
    print(f"  Profile:     {args.profile}")
    print(f"  Concurrency: {args.concurrency} workers")
    print(f"  Duration:    {args.duration}s")
    print(f"  Replicas:    {args.replicas} (label only)")
    print(f"  Query bank:  {len(query_bank)} queries")
    perturb = not args.no_perturb

    # Resolve effective k and top values
    if args.expensive:
        effective_k = 500
        effective_top = 50
    else:
        effective_k = args.k if args.k is not None else 5
        effective_top = args.top if args.top is not None else effective_k

    if args.log_requests:
        print(f"  Log mode:    per-request JSONL enabled")
    print(f"  Cache-bust:  {'disabled (--no-perturb)' if not perturb else 'ON — tiny noise added to each query vector'}")
    print(f"  Retries:     {args.retry_total} ({'SDK default — 503s silently retried' if args.retry_total > 0 else 'disabled — 503s surface as errors'})")
    if args.expensive:
        print(f"  Expensive:   ON — k=500, top=50 (simulates large-index query cost)")
    else:
        print(f"  k_nearest:   {effective_k}  (LangChain default=4; production often 50–100)")
        print(f"  top:         {effective_top}")
    if args.oversampling is not None:
        effective_candidates = effective_k * args.oversampling
        print(f"  oversampling:{args.oversampling}  (internal candidates: {effective_k} × {args.oversampling} = {effective_candidates})")
    print()

    started_at = datetime.now(timezone.utc)
    end_time = time.monotonic() + args.duration

    raw_results: list[tuple[int, float]] = []
    counters = {"total": 0, "throttled": 0, "errors_503": 0}

    service_name = endpoint.split("//")[-1].split(".")[0]

    out_dir = run_dir(started_at, args)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "log.jsonl"

    async with SearchClient(
        endpoint=endpoint,
        index_name=index,
        credential=credential,
        retry_total=args.retry_total,
    ) as client:
        if args.profile == "semantic":
            print("Checking semantic ranker availability ...")
            await preflight_semantic_check(
                client, random.choice(query_bank), semantic_config, service_name
            )
            print("  Semantic ranker OK\n")

        # Progress reporter coroutine
        async def progress_reporter():
            interval = 5
            while time.monotonic() < end_time:
                await asyncio.sleep(interval)
                elapsed = args.duration - max(0, end_time - time.monotonic())
                qps = counters["total"] / max(elapsed, 1)
                print(
                    f"  [{elapsed:4.0f}s] total={counters['total']:4d}  "
                    f"429s={counters['throttled']:3d}  "
                    f"503s={counters['errors_503']:3d}  "
                    f"qps={qps:.1f}"
                )

        log_state = None
        log_fh = None
        if args.log_requests:
            log_fh = open(log_path, "w", encoding="utf-8")
            log_state = {"lock": asyncio.Lock(), "seq": 0, "fh": log_fh}

        try:
            workers = [
                run_worker(
                    i, client, query_bank, args.profile, semantic_config,
                    end_time, raw_results, counters, log_state, perturb,
                    args.expensive, effective_k, effective_top, args.oversampling,
                )
                for i in range(args.concurrency)
            ]
            await asyncio.gather(progress_reporter(), *workers)
        finally:
            if log_fh:
                log_fh.close()

    stats = aggregate_results(raw_results, args.duration)
    out_dir = write_results(args, stats, started_at, k=effective_k, top=effective_top, oversampling=args.oversampling)

    print()
    print("=== Results ===")
    print(f"  Total requests : {stats['total_requests']}")
    print(f"  Successful     : {stats['successful']}")
    print(f"  Throttled 429  : {stats['throttled_429']}  ({stats['throttle_pct']}%)")
    print(f"  Overloaded 503 : {stats['errors_503']}  ({stats['error_503_pct']}%)")
    print(f"  p50 latency    : {stats['p50_ms']} ms")
    print(f"  p95 latency    : {stats['p95_ms']} ms")
    print(f"  p99 latency    : {stats['p99_ms']} ms")
    print(f"  Achieved QPS   : {stats['achieved_qps']}")
    print()
    print(f"Run directory:  {out_dir}/")
    print(f"  summary.json  — aggregated stats (read by advisor.py)")
    if args.log_requests:
        print(f"  log.jsonl     — per-request detail ({stats['total_requests']} entries)")
        print(f"                  fields: query, profile, latency_ms, results[]")
        print(f"                  semantic runs add: reranker_score, captions")


def main() -> None:
    args = parse_args()
    asyncio.run(run_load_test(args))


if __name__ == "__main__":
    main()
