"""
Direct MCP tool-call seeder for MCPForge validation.
Replaces the original Truefoundry-based seeder.

Connects to the MCPForge proxy at http://localhost:8765/sse and fires
realistic incident-response tool calls. HOT tools (datadog, slack, kubernetes,
pagerduty) get called many times; COLD tools (github, sentry, confluence, jira,
linear, notion) get 0 calls. After this runs, the optimizer should score and
prune the cold tools.

Usage:
    python seed_metrics.py [--proxy http://localhost:8765/sse]
"""

import argparse
import asyncio
import random
import time

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

PROXY_URL = "http://localhost:8765/sse"

# (tool_name, arguments, call_count)
# HOT tools — called many times to build high scores
HOT_CALLS = [
    # datadog — 8 prompts each for query_metrics, search_logs; fewer for others
    ("query_metrics", {"service": "payment-service", "metric": "latency", "window_minutes": 15}, 8),
    ("query_metrics", {"service": "auth-service", "metric": "request_rate", "window_minutes": 30}, 6),
    ("query_metrics", {"service": "api-gateway", "metric": "cpu_util", "window_minutes": 20}, 4),
    ("list_monitors", {"status_filter": "Alert"}, 5),
    ("get_dashboard", {"dashboard_id": "dash-prod-001"}, 3),
    ("search_logs", {"query": "ConnectionError", "service": "payment-service", "limit": 50}, 6),
    ("search_logs", {"query": "ERROR", "service": "auth-service", "limit": 50}, 4),
    ("silence_monitor", {"monitor_id": "mon_1001", "duration_minutes": 30}, 3),
    # slack
    ("send_message", {"channel": "#incidents", "text": "P1 incident declared — payment service latency degraded. Bridge open."}, 7),
    ("send_message", {"channel": "#oncall-alerts", "text": "Investigating latency spike."}, 5),
    ("post_to_channel", {"channel": "#incidents", "blocks": [{"type": "section", "text": "Incident update"}]}, 3),
    ("create_thread", {"channel": "#incidents", "text": "Payment-service outage thread"}, 3),
    # kubernetes
    ("restart_pod", {"pod_name": "payment-processor", "namespace": "production"}, 5),
    ("restart_pod", {"pod_name": "auth-worker", "namespace": "production"}, 3),
    ("get_pod_logs", {"pod_name": "payment-processor", "namespace": "production", "tail_lines": 200}, 5),
    ("get_pod_logs", {"pod_name": "api-gateway", "namespace": "production", "tail_lines": 100}, 3),
    ("scale_deployment", {"deployment": "payment-service", "replicas": 8, "namespace": "production"}, 4),
    ("scale_deployment", {"deployment": "auth-service", "replicas": 6, "namespace": "production"}, 3),
    # pagerduty
    ("escalate_incident", {"incident_id": "INC-4521", "escalation_policy_id": "platform-engineering"}, 3),
    ("acknowledge_alert", {"alert_id": "ALT-001"}, 3),
    ("acknowledge_alert", {"alert_id": "ALT-334"}, 2),
]


async def seed(proxy_url: str) -> None:
    print(f"Connecting to MCPForge proxy: {proxy_url}")
    print()

    async with sse_client(proxy_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Discover tools
            tool_list = await session.list_tools()
            available = {t.name for t in tool_list.tools}
            print(f"tools/list returned {len(available)} tools in cold-start pool")
            print()

            total_calls = sum(count for _, _, count in HOT_CALLS)
            made = 0
            skipped = 0

            for tool_name, args, count in HOT_CALLS:
                if tool_name not in available:
                    print(f"  SKIP  {tool_name} (not in proxy pool)")
                    skipped += count
                    continue

                for i in range(count):
                    made += 1
                    t0 = time.perf_counter()
                    try:
                        result = await session.call_tool(tool_name, args)
                        elapsed = (time.perf_counter() - t0) * 1000
                        status = "ok" if not result.isError else "err"
                        print(f"  [{made:03d}] {tool_name:<30} {elapsed:6.1f}ms  [{status}]")
                    except Exception as exc:
                        print(f"  [{made:03d}] {tool_name:<30} ERROR: {exc}")

                    # small delay to spread timestamps slightly
                    await asyncio.sleep(0.05)

    print()
    print(f"Done. {made} tool calls made, {skipped} skipped (not in pool).")
    print("HOT servers: datadog-mcp, slack-mcp, kubernetes-mcp, pagerduty-mcp")
    print("COLD servers (0 calls): github-mcp, sentry-mcp, confluence-mcp, jira-mcp, linear-mcp, notion-mcp")


def main():
    parser = argparse.ArgumentParser(description="Seed MCPForge with incident tool calls")
    parser.add_argument("--proxy", default=PROXY_URL, help="MCPForge SSE endpoint")
    args = parser.parse_args()
    asyncio.run(seed(args.proxy))


if __name__ == "__main__":
    main()
