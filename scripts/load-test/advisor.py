#!/usr/bin/env python3
"""
advisor.py — Reads load test result files and prints scaling recommendations.

Usage:
    python advisor.py results/
    python advisor.py results/2026-05-21T14-30_c20_hybrid_r1.json  (single file)

Reads all JSON files in the given directory (or the single file provided),
groups runs by replica count and profile, applies threshold rules, and prints
a human-readable report with findings and recommendations.
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ADVISORY_DIR = SCRIPT_DIR / "advisory"


# --- Threshold constants ---
THROTTLE_WARN_PCT = 1.0    # early warning
THROTTLE_HIGH_PCT = 5.0    # replica recommendation triggered
LATENCY_HIGH_MS = 800      # p95 high latency (no 429s)
LATENCY_SEMANTIC_MS = 1000 # p95 high latency for semantic profile
LATENCY_HEALTHY_MS = 300   # p95 healthy threshold


def load_results(path_arg: str) -> list[dict]:
    p = Path(path_arg)
    if p.is_file():
        files = [p]
    elif p.is_dir():
        # New layout: results/<run-dir>/summary.json
        files = sorted(p.glob("*/summary.json"))
        # Backward compat: flat *.json files directly in the directory
        files += sorted(f for f in p.glob("*.json") if f.name != "summary.json")
    else:
        sys.exit(f"ERROR: '{path_arg}' is not a valid file or directory.")

    if not files:
        sys.exit(f"ERROR: No summary.json files found in '{path_arg}'.\nRun load_test.py first.")

    results = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_file"] = f.parent.name if f.name == "summary.json" else f.name
            results.append(data)
        except Exception as exc:
            print(f"  WARNING: Could not parse {f.name}: {exc}", file=sys.stderr)

    if not results:
        sys.exit("ERROR: No valid result files could be loaded.")

    return results


def group_by_profile_replicas(results: list[dict]) -> dict:
    """
    Returns: {profile: {replicas: [result, ...]}}
    """
    grouped: dict = {}
    for r in results:
        profile = r.get("profile", "unknown")
        replicas = r.get("replicas", 1)
        grouped.setdefault(profile, {}).setdefault(replicas, []).append(r)
    return grouped


def best_run(runs: list[dict]) -> dict:
    """Pick the run with the most requests (longest / most recent meaningful run)."""
    return max(runs, key=lambda r: r.get("total_requests", 0))


def replica_recommendation(run: dict, target_qps: float | None = None) -> int:
    """
    Formula: ceil(target_qps / (achieved_qps / replicas)) * 1.2 buffer
    If target_qps is not provided, use achieved_qps * 2 as a conservative target.
    """
    replicas = run.get("replicas", 1)
    achieved_qps = run.get("achieved_qps", 1.0) or 1.0
    if target_qps is None:
        target_qps = achieved_qps * 2
    qps_per_replica = achieved_qps / replicas
    raw = math.ceil(target_qps / qps_per_replica)
    return math.ceil(raw * 1.2)  # 20% buffer


def pct_change(before: float, after: float) -> str:
    if before == 0:
        return "N/A"
    pct = (after - before) / before * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.0f}%"


def print_comparison_table(profile: str, replica_groups: dict) -> None:
    replica_counts = sorted(replica_groups.keys())
    if len(replica_counts) < 2:
        return

    print(f"\n  Before/After comparison — {profile} profile:")
    header = f"  {'Replicas':>8}  {'p50 ms':>7}  {'p95 ms':>7}  {'p99 ms':>7}  {'429 rate':>8}  {'QPS':>6}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    first_run = None
    for rep in replica_counts:
        run = best_run(replica_groups[rep])
        print(
            f"  {rep:>8}  "
            f"{run.get('p50_ms', 0):>7.0f}  "
            f"{run.get('p95_ms', 0):>7.0f}  "
            f"{run.get('p99_ms', 0):>7.0f}  "
            f"{run.get('throttle_pct', 0):>7.1f}%  "
            f"{run.get('achieved_qps', 0):>6.1f}"
        )
        if first_run is None:
            first_run = run

    # Percentage improvement between first and last replica count
    last_run = best_run(replica_groups[replica_counts[-1]])
    p95_change = pct_change(first_run.get("p95_ms", 0), last_run.get("p95_ms", 0))
    rate_change = pct_change(first_run.get("throttle_pct", 0), last_run.get("throttle_pct", 0))
    print(f"\n  p95 change from r{replica_counts[0]} to r{replica_counts[-1]}: {p95_change}")
    print(f"  429 rate change: {rate_change}")


def print_semantic_ranker_impact(grouped: dict) -> None:
    """
    When both 'hybrid' and 'semantic' results exist at the same concurrency + replica count,
    print a side-by-side comparison showing the semantic ranker's effect on latency.
    """
    if "hybrid" not in grouped or "semantic" not in grouped:
        return

    # Find replica counts present in both profiles
    hybrid_replicas = set(grouped["hybrid"].keys())
    semantic_replicas = set(grouped["semantic"].keys())
    common_replicas = sorted(hybrid_replicas & semantic_replicas)
    if not common_replicas:
        return

    print("--- Semantic Ranker Impact (hybrid vs semantic, same concurrency) ---")
    header = f"  {'Replicas':>8}  {'Profile':>8}  {'p50 ms':>7}  {'p95 ms':>7}  {'p99 ms':>7}  {'429 rate':>8}  {'QPS':>6}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for rep in common_replicas:
        h = best_run(grouped["hybrid"][rep])
        s = best_run(grouped["semantic"][rep])
        for label, run in [("hybrid", h), ("semantic", s)]:
            print(
                f"  {rep:>8}  "
                f"  {label:>8}  "
                f"{run.get('p50_ms', 0):>7.0f}  "
                f"{run.get('p95_ms', 0):>7.0f}  "
                f"{run.get('p99_ms', 0):>7.0f}  "
                f"{run.get('throttle_pct', 0):>7.1f}%  "
                f"{run.get('achieved_qps', 0):>6.1f}"
            )
        h_p95 = h.get("p95_ms", 0)
        s_p95 = s.get("p95_ms", 0)
        delta = s_p95 - h_p95
        sign = "+" if delta >= 0 else ""
        print(f"\n  Semantic ranker p95 overhead @ {rep} replica(s): {sign}{delta:.0f}ms ({pct_change(h_p95, s_p95)})")

    print(
        "\n  NOTE: The semantic ranker re-ranks hybrid results using a neural model.\n"
        "  Higher latency reflects the re-ranking step, not replica saturation.\n"
    )


def generate_markdown(results: list[dict], grouped: dict, findings: list[str], recommendations: list[str]) -> str:
    profiles = sorted(grouped.keys())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # collect all runs for the summary table
    rows = []
    for profile in profiles:
        for rep in sorted(grouped[profile].keys()):
            run = best_run(grouped[profile][rep])
            rows.append((profile, rep, run))

    lines = [
        "# Azure AI Search Load Test Report",
        "",
        f"**Generated:** {now}  ",
        f"**Profiles tested:** {', '.join(profiles)}  ",
        f"**Replicas:** {', '.join(str(r) for r in sorted({run.get('replicas',1) for _,_,run in rows}))}  ",
        f"**Concurrency:** {rows[0][2].get('concurrency','?')} workers, {rows[0][2].get('duration_s','?')}s duration  ",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Profile | Replicas | p50 ms | p95 ms | p99 ms | QPS | 429 rate |",
        "|---------|----------|--------|--------|--------|-----|----------|",
    ]
    for profile, rep, run in rows:
        lines.append(
            f"| {profile} | {rep} | {run.get('p50_ms',0):.0f} | {run.get('p95_ms',0):.0f} | "
            f"{run.get('p99_ms',0):.0f} | {run.get('achieved_qps',0):.1f} | {run.get('throttle_pct',0):.1f}% |"
        )

    # Semantic ranker impact section
    if "hybrid" in grouped and "semantic" in grouped:
        hybrid_replicas = set(grouped["hybrid"].keys())
        semantic_replicas = set(grouped["semantic"].keys())
        common_replicas = sorted(hybrid_replicas & semantic_replicas)
        if common_replicas:
            lines += [
                "",
                "---",
                "",
                "## Semantic Ranker Impact",
                "",
                "> **Why only hybrid vs semantic?**  ",
                "> `semantic` = `hybrid` + neural L2 re-ranker applied to the top-50 hybrid candidates.  ",
                "> Comparing these two isolates exactly what the ranker adds in latency and QPS cost.  ",
                "> `vector` uses different retrieval (no BM25 keyword) so it is not a meaningful baseline here.",
                "",
                "| Profile | p50 ms | p95 ms | p99 ms | QPS | 429 rate |",
                "|---------|--------|--------|--------|-----|----------|",
            ]
            for rep in common_replicas:
                h = best_run(grouped["hybrid"][rep])
                s = best_run(grouped["semantic"][rep])
                for label, run in [("hybrid", h), ("semantic", s)]:
                    lines.append(
                        f"| {label} | {run.get('p50_ms',0):.0f} | {run.get('p95_ms',0):.0f} | "
                        f"{run.get('p99_ms',0):.0f} | {run.get('achieved_qps',0):.1f} | {run.get('throttle_pct',0):.1f}% |"
                    )
                h_p95 = h.get("p95_ms", 0)
                s_p95 = s.get("p95_ms", 0)
                delta = s_p95 - h_p95
                lines += [
                    "",
                    f"**Ranker p95 overhead @ {rep} replica(s):** +{delta:.0f}ms ({pct_change(h_p95, s_p95)})  ",
                    f"**QPS impact:** {h.get('achieved_qps',0):.1f} → {s.get('achieved_qps',0):.1f} "
                    f"({pct_change(h.get('achieved_qps',0), s.get('achieved_qps',0))})  ",
                    "",
                    "_Higher latency reflects the re-ranking step, not replica saturation._",
                ]

    # Findings
    lines += ["", "---", "", "## Findings", ""]
    EMOJI = {
        "HEALTHY": "✅", "SEMANTIC_OVERHEAD": "ℹ️", "THROTTLING": "🚨",
        "THROTTLE_WARN": "⚠️", "LATENCY": "⚠️", "SEMANTIC_QUOTA": "⚠️",
    }
    if findings:
        for f in findings:
            tag = f.split("]")[0].lstrip("[") if "]" in f else ""
            emoji = EMOJI.get(tag, "•")
            lines.append(f"- {emoji} {f}")
    else:
        lines.append("_No issues detected._")

    # Recommendations
    lines += ["", "---", "", "## Recommendations", ""]
    if recommendations:
        for i, rec in enumerate(recommendations, start=1):
            lines.append(f"{i}. {rec}")
    else:
        lines.append("_No scaling recommendations at current concurrency._")

    # KQL
    lines += [
        "", "---", "",
        "## Log Analytics",
        "",
        "See [`kql/README.md`](kql/README.md) for queries to run in a Log Analytics workspace.",
        "",
        "| Query file | Purpose |",
        "|------------|---------|",
        "| `kql/throttling.kql` | 429 rate by 5-minute window |",
        "| `kql/latency.kql` | p50/p95/p99 latency trend |",
        "| `kql/semantic-impact.kql` | Before/after latency when enabling semantic ranker |",
    ]

    return "\n".join(lines) + "\n"


def analyze(results: list[dict]) -> tuple[dict, list[str], list[str]]:
    grouped = group_by_profile_replicas(results)
    findings: list[str] = []
    recommendations: list[str] = []

    print("=== Azure AI Search Load Test Report ===\n")
    print(f"  Result files loaded: {len(results)}")
    profiles = sorted(grouped.keys())
    print(f"  Profiles found:      {', '.join(profiles)}")
    print()

    for profile in profiles:
        replica_groups = grouped[profile]
        replica_counts = sorted(replica_groups.keys())
        print(f"--- Profile: {profile} ---")

        for rep in replica_counts:
            run = best_run(replica_groups[rep])
            print(
                f"  Replicas={rep:<2}  "
                f"concurrency={run.get('concurrency', '?')}  "
                f"duration={run.get('duration_s', '?')}s  "
                f"requests={run.get('total_requests', 0)}  "
                f"p95={run.get('p95_ms', 0):.0f}ms  "
                f"429_rate={run.get('throttle_pct', 0):.1f}%  "
                f"QPS={run.get('achieved_qps', 0):.1f}"
            )

        # Use the lowest-replica run for threshold analysis
        base_run = best_run(replica_groups[replica_counts[0]])
        throttle_pct = base_run.get("throttle_pct", 0.0)
        p95_ms = base_run.get("p95_ms", 0.0)
        replicas = base_run.get("replicas", 1)

        # THROTTLING finding
        if throttle_pct > THROTTLE_HIGH_PCT:
            findings.append(
                f"[THROTTLING]  {profile} profile @ {replicas} replica(s): "
                f"{throttle_pct:.1f}% of requests were throttled (HTTP 429). "
                f"Customers will see intermittent failures at this concurrency."
            )
            rec_replicas = replica_recommendation(base_run)
            recommendations.append(
                f"Add replicas to handle current load (minimum 3 for read SLA).\n"
                f"    Estimated replicas needed: {rec_replicas}\n"
                f"    az search service update --replica-count {rec_replicas} ..."
            )
        elif throttle_pct >= THROTTLE_WARN_PCT:
            findings.append(
                f"[THROTTLE_WARN]  {profile} profile @ {replicas} replica(s): "
                f"{throttle_pct:.1f}% 429 rate — early warning. "
                f"Add 1-2 replicas proactively."
            )

        # SEMANTIC_QUOTA finding (semantic profile, high p95, no throttle)
        if profile == "semantic" and p95_ms > LATENCY_SEMANTIC_MS:
            findings.append(
                f"[SEMANTIC_QUOTA]  Semantic profile p95={p95_ms:.0f}ms. "
                f"The semantic ranker has its own quota separate from replica QPS. "
                f"High latency may reflect ranker saturation, not replica saturation."
            )
            recommendations.append(
                "Limit semantic reranking scope: reduce top-N results sent to the ranker\n"
                "    (e.g., top=5 instead of top=20) to reduce semantic ranker pressure."
            )
        # LATENCY finding (no throttling, but high p95)
        elif p95_ms > LATENCY_HIGH_MS and throttle_pct == 0.0:
            findings.append(
                f"[LATENCY]  {profile} profile p95={p95_ms:.0f}ms with 0% throttle rate. "
                f"High latency without throttling suggests query complexity rather than "
                f"replica saturation."
            )
            recommendations.append(
                "Check semantic reranking scope and query complexity.\n"
                "    Consider reducing the number of results retrieved per query,\n"
                "    or switching from 'semantic' to 'hybrid' profile for non-critical queries."
            )
        # SEMANTIC_OVERHEAD finding — expected ranker cost, not a problem
        elif profile == "semantic" and LATENCY_HEALTHY_MS <= p95_ms < LATENCY_SEMANTIC_MS and throttle_pct == 0.0:
            findings.append(
                f"[SEMANTIC_OVERHEAD]  Semantic profile p95={p95_ms:.0f}ms — expected neural "
                f"re-ranking overhead (hybrid baseline is typically 3–4x faster). "
                f"No throttling; service is healthy. This latency is the ranker cost, not replica saturation."
            )
        # HEALTHY finding
        elif p95_ms < LATENCY_HEALTHY_MS and throttle_pct == 0.0:
            findings.append(
                f"[HEALTHY]  {profile} profile @ {replicas} replica(s): "
                f"p95={p95_ms:.0f}ms, 429_rate=0.0% — within acceptable bounds "
                f"at current concurrency."
            )

        # Before/after comparison table
        if len(replica_counts) > 1:
            print_comparison_table(profile, replica_groups)

        print()

    # Semantic ranker impact comparison
    print_semantic_ranker_impact(grouped)

    # Print findings
    print("Findings:")
    if findings:
        for f in findings:
            print(f"  {f}")
    else:
        print("  No issues detected.")
    print()

    # Print recommendations
    if recommendations:
        print("Recommendations:")
        for i, rec in enumerate(recommendations, start=1):
            print(f"  {i}. {rec}")
        print()

    # KQL pointer
    print(f"Log Analytics queries: kql/README.md")
    print("  Run kql/throttling.kql and kql/latency.kql in your Log Analytics workspace")
    print("  to observe the same patterns from the service's own diagnostic logs.")

    return grouped, findings, recommendations


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Azure AI Search load test advisor")
    parser.add_argument("results_path", nargs="?",
                        default=str(SCRIPT_DIR / "results"),
                        help="Path to results directory or a single summary.json file")
    parser.add_argument("--report", action="store_true",
                        help="Save a Markdown report to advisory/<timestamp>_report.md")
    args = parser.parse_args()

    results = load_results(args.results_path)
    grouped, findings, recommendations = analyze(results)

    if args.report:
        ADVISORY_DIR.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")
        report_path = ADVISORY_DIR / f"{ts}_report.md"
        md = generate_markdown(results, grouped, findings, recommendations)
        report_path.write_text(md, encoding="utf-8")
        print(f"\nMarkdown report saved to: {report_path}")


if __name__ == "__main__":
    main()
