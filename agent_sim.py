"""
agent_sim.py

Simulates N concurrent external agents connecting to MCPForge and completing
realistic oncall tasks. Each agent:
  1. Connects to the MCPForge SSE endpoint and discovers tools via tools/list
  2. Receives a task (randomly assigned from TASKS)
  3. Runs a Claude agentic loop — the LLM decides which tools to call
  4. All tool calls go through MCPForge, which logs them for the optimizer

This produces realistic, LLM-driven usage signal rather than the scripted
call sequence in load_test.py.

Usage:
  python agent_sim.py [--url URL] [--agents N] [--tasks-per-agent M] [--model MODEL]
"""

import argparse
import asyncio
import json
import os
import random
import time
from dotenv import load_dotenv

load_dotenv(".env")

import anthropic
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

PROXY_URL = "https://mcp-tool-optimizer-production.up.railway.app/sse"
MODEL = "claude-haiku-4-5-20251001"

# Realistic oncall tasks across incident, planning, and general session types.
# Variety here is intentional — different tasks should drive different tool selections.
TASKS = [
    # --- Incident ---
    "api-gateway error rate just spiked to 18%. Check the metrics, find relevant error logs, and tell me what's happening.",
    "PagerDuty fired an alert. List all monitors currently in Alert or Warn state and summarize what's firing.",
    "auth-service p99 latency is at 3.4s. Query the last 10 minutes of latency metrics and search the logs for timeouts.",
    "We're seeing pod crashes in the prod namespace. Get logs from the api-gateway pod and check if we need to restart it.",
    "Payment service is down. Escalate incident INC-2048 to the on-call escalation policy EP001 immediately.",
    "Check if there are any open alerts right now across all monitors. Give me a status summary.",
    "The Kubernetes api-gateway deployment is falling behind traffic. Scale it to 8 replicas.",
    "Search for OOMKilled errors in logs across api-gateway and auth-service in the last hour.",

    # --- Planning / general ---
    "List all repositories in the company GitHub org and tell me which ones seem active.",
    "Search Confluence for runbooks tagged 'incident-response' and summarize what you find.",
    "Find all open Jira tickets related to latency issues and list them.",
    "Post a Slack update to #incidents: 'api-gateway degraded performance, team investigating, ETA 20 min'.",
    "Check Sentry for the most recent unresolved errors in the checkout service.",
    "List all Kubernetes namespaces and tell me which ones are running production workloads.",
    "Search Linear for any issues assigned to the oncall team this week.",
    "Check Notion for any on-call handoff notes from the last 24 hours.",
]


def mcp_tool_to_anthropic(tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
    }


async def run_agent(agent_id: int, tasks: list[str], proxy_url: str) -> list[dict]:
    results = []
    client = anthropic.AsyncAnthropic()

    for task in tasks:
        t0 = time.perf_counter()
        calls_made = []
        total_input = 0
        total_output = 0
        error = None

        try:
            async with sse_client(proxy_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # Discover tools through MCPForge (gets the active/optimized pool)
                    tool_list = (await session.list_tools()).tools
                    anthropic_tools = [mcp_tool_to_anthropic(t) for t in tool_list]

                    messages = [{"role": "user", "content": task}]

                    # Agentic loop — Claude decides which tools to call
                    for _ in range(10):  # max 10 turns per task
                        resp = await client.messages.create(
                            model=MODEL,
                            max_tokens=1024,
                            tools=anthropic_tools,
                            messages=messages,
                        )
                        total_input += resp.usage.input_tokens
                        total_output += resp.usage.output_tokens

                        if resp.stop_reason == "end_turn":
                            break

                        # Execute tool calls through MCPForge
                        tool_results = []
                        for block in resp.content:
                            if block.type == "tool_use":
                                calls_made.append(block.name)
                                try:
                                    result = await session.call_tool(block.name, block.input)
                                    content = ""
                                    for c in (result.content or []):
                                        if hasattr(c, "text"):
                                            content += c.text
                                        elif hasattr(c, "model_dump"):
                                            content += json.dumps(c.model_dump())
                                    tool_results.append({
                                        "type": "tool_result",
                                        "tool_use_id": block.id,
                                        "content": content[:2000],
                                    })
                                except Exception as e:
                                    tool_results.append({
                                        "type": "tool_result",
                                        "tool_use_id": block.id,
                                        "content": f"error: {e}",
                                        "is_error": True,
                                    })

                        messages.append({"role": "assistant", "content": resp.content})
                        messages.append({"role": "user", "content": tool_results})

        except Exception as e:
            error = str(e)

        elapsed = time.perf_counter() - t0
        results.append({
            "agent_id": agent_id,
            "task": task[:60] + ("…" if len(task) > 60 else ""),
            "calls_made": calls_made,
            "unique_tools": list(dict.fromkeys(calls_made)),  # ordered dedup
            "total_calls": len(calls_made),
            "input_tokens": total_input,
            "output_tokens": total_output,
            "elapsed_s": round(elapsed, 2),
            "error": error,
        })

        status = "ok" if not error else "err"
        tools_str = " → ".join(calls_made) if calls_made else "(no tools called)"
        print(f"  [agent {agent_id:02d}] [{status}] {results[-1]['task']}")
        if error:
            print(f"             error: {error}")
        print(f"             tools: {tools_str}")
        print(f"             {len(calls_made)} calls | {total_input + total_output} tokens | {elapsed:.1f}s")

    return results


def print_summary(all_results: list[dict], elapsed_total: float):
    W = 62
    print("\n" + "=" * W)
    print("  AGENT SIMULATION SUMMARY")
    print("=" * W)

    total_tasks = len(all_results)
    ok_tasks = sum(1 for r in all_results if not r["error"])
    total_calls = sum(r["total_calls"] for r in all_results)
    total_tokens = sum(r["input_tokens"] + r["output_tokens"] for r in all_results)

    # Tool frequency across all tasks
    tool_freq: dict[str, int] = {}
    for r in all_results:
        for t in r["calls_made"]:
            tool_freq[t] = tool_freq.get(t, 0) + 1

    print(f"  Tasks completed      {ok_tasks:>6} / {total_tasks}")
    print(f"  Total tool calls     {total_calls:>6}")
    print(f"  Total tokens         {total_tokens:>6,}")
    print(f"  Elapsed              {elapsed_total:>6.1f}s")
    print(f"  Unique tools hit     {len(tool_freq):>6}")
    print("-" * W)
    print("  Tool call frequency (all agents):")
    for tool, count in sorted(tool_freq.items(), key=lambda x: -x[1]):
        bar = "█" * min(count, 30)
        print(f"    {tool:<30} {count:>4}  {bar}")
    print("=" * W)


async def main(num_agents: int, tasks_per_agent: int, proxy_url: str):
    print(f"\nAgent simulation: {num_agents} agents × {tasks_per_agent} tasks")
    print(f"Proxy: {proxy_url}\n")

    # Assign tasks randomly to agents
    agent_task_lists = [
        random.sample(TASKS, min(tasks_per_agent, len(TASKS)))
        for _ in range(num_agents)
    ]

    t0 = time.perf_counter()
    agent_coroutines = [
        run_agent(i, agent_task_lists[i], proxy_url)
        for i in range(num_agents)
    ]
    all_results_nested = await asyncio.gather(*agent_coroutines)
    elapsed = time.perf_counter() - t0

    all_results = [r for agent_results in all_results_nested for r in agent_results]
    print_summary(all_results, elapsed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url",              type=str, default=PROXY_URL)
    parser.add_argument("--agents",           type=int, default=5)
    parser.add_argument("--tasks-per-agent",  type=int, default=3)
    parser.add_argument("--model",            type=str, default=MODEL)
    args = parser.parse_args()
    MODEL = args.model
    asyncio.run(main(args.agents, args.tasks_per_agent, args.url))
