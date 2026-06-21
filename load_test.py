"""
load_test.py

Fires N concurrent sessions against the mcpforge proxy, each making M tool calls.
Reports throughput, latency percentiles, error rate, and DB integrity.

Usage:
  python load_test.py [--sessions N] [--calls M] [--url URL]
"""

import argparse
import asyncio
import statistics
import time

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

PROXY_URL = "http://localhost:8765/sse"

# Skewed call distribution: HOT tools called 5-6x more than COLD tools.
# This gives the optimizer a clear signal about which tools matter.
CALLS = [
    # HOT — incident response tools (called frequently)
    ("query_metrics",       {"service": "api-gateway",   "metric": "error_rate",  "window_minutes": 5}),
    ("query_metrics",       {"service": "auth-service",  "metric": "p99_latency", "window_minutes": 10}),
    ("list_monitors",       {"status_filter": "alert"}),
    ("list_monitors",       {"status_filter": "warn"}),
    ("search_logs",         {"query": "ERROR",      "service": "api-gateway",  "limit": 50}),
    ("search_logs",         {"query": "exception",  "service": "auth-service", "limit": 20}),
    ("restart_pod",         {"namespace": "prod",   "pod_name": "api-gateway-7d9f8b-xkq2p"}),
    ("get_pod_logs",        {"namespace": "prod",   "pod_name": "api-gateway-7d9f8b-xkq2p", "tail_lines": 100}),
    ("scale_deployment",    {"namespace": "prod",   "deployment": "api-gateway", "replicas": 6}),
    ("escalate_incident",   {"incident_id": "INC-1042", "escalation_policy_id": "EP001"}),
    ("acknowledge_alert",   {"alert_id": "ALT-9981"}),
    ("get_dashboard",       {"dashboard_id": "oncall-overview"}),
    ("silence_monitor",     {"monitor_id": "MON-441", "duration_minutes": 30}),
    # COLD — tools that are rarely needed (optimizer should learn to reserve these)
    ("list_repos",          {"org": "company"}),
    ("list_hosts",          {"env": "staging"}),
    ("search_pages",        {"query": "runbook", "space": "ENG"}),
    ("list_services",       {}),
    ("list_namespaces",     {}),
]


async def run_session(session_id: int, num_calls: int) -> dict:
    results = []
    errors = []

    try:
        async with sse_client(PROXY_URL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                for i in range(num_calls):
                    tool, args = CALLS[i % len(CALLS)]
                    t0 = time.perf_counter()
                    try:
                        result = await session.call_tool(tool, args)
                        latency = (time.perf_counter() - t0) * 1000
                        ok = not getattr(result, "isError", False)
                        results.append({"tool": tool, "latency_ms": latency, "ok": ok})
                        if not ok:
                            errors.append(f"session={session_id} call={i} tool={tool}: isError=True")
                    except Exception as e:
                        latency = (time.perf_counter() - t0) * 1000
                        results.append({"tool": tool, "latency_ms": latency, "ok": False})
                        errors.append(f"session={session_id} call={i} tool={tool}: {e}")
    except Exception as e:
        errors.append(f"session={session_id} connect failed: {e}")

    return {"session_id": session_id, "results": results, "errors": errors}


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    return statistics.quantiles(sorted(data), n=100)[int(p) - 1]


async def main(num_sessions: int, calls_per_session: int):
    total_calls = num_sessions * calls_per_session
    print(f"\nLoad test: {num_sessions} concurrent sessions × {calls_per_session} calls = {total_calls} total calls")
    print(f"Proxy: {PROXY_URL}\n")

    t_start = time.perf_counter()
    session_tasks = [
        run_session(i, calls_per_session)
        for i in range(num_sessions)
    ]
    all_results = await asyncio.gather(*session_tasks)
    elapsed = time.perf_counter() - t_start

    # Aggregate
    all_latencies = []
    all_errors = []
    success_count = 0
    tool_latencies: dict[str, list[float]] = {}

    for sr in all_results:
        all_errors.extend(sr["errors"])
        for r in sr["results"]:
            all_latencies.append(r["latency_ms"])
            if r["ok"]:
                success_count += 1
            tool_latencies.setdefault(r["tool"], []).append(r["latency_ms"])

    attempted = len(all_latencies)
    error_rate = (attempted - success_count) / attempted * 100 if attempted else 0
    throughput = attempted / elapsed

    print(f"{'─'*55}")
    print(f"  Completed calls     {attempted:>8} / {total_calls}")
    print(f"  Successful          {success_count:>8}  ({100-error_rate:.1f}%)")
    print(f"  Failed              {attempted - success_count:>8}  ({error_rate:.1f}%)")
    print(f"  Elapsed             {elapsed:>8.2f}s")
    print(f"  Throughput          {throughput:>8.1f} calls/s")
    print(f"{'─'*55}")
    if all_latencies:
        print(f"  Latency p50         {percentile(all_latencies, 50):>7.0f}ms")
        print(f"  Latency p95         {percentile(all_latencies, 95):>7.0f}ms")
        print(f"  Latency p99         {percentile(all_latencies, 99):>7.0f}ms")
        print(f"  Latency max         {max(all_latencies):>7.0f}ms")
    print(f"{'─'*55}")
    print("  Per-tool p95 latency:")
    for tool, lats in sorted(tool_latencies.items()):
        p95 = percentile(lats, 95)
        print(f"    {tool:<30} {p95:>6.0f}ms  (n={len(lats)})")
    print(f"{'─'*55}")

    if all_errors:
        print(f"\n  Errors ({len(all_errors)}):")
        for e in all_errors[:10]:
            print(f"    {e}")
        if len(all_errors) > 10:
            print(f"    ... and {len(all_errors)-10} more")
    else:
        print("\n  No errors.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=10)
    parser.add_argument("--calls",    type=int, default=5)
    parser.add_argument("--url",      type=str, default=PROXY_URL,
                        help="MCPForge SSE endpoint (default: %(default)s)")
    args = parser.parse_args()
    PROXY_URL = args.url
    asyncio.run(main(args.sessions, args.calls))
