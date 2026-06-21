"""
compare_pools.py

Runs the same task against two tool pools:
  - FULL:      all 40 tools from both MCP servers
  - OPTIMIZED: only the 8 active tools from the mcpforge proxy

Measures and prints:
  - Schema tokens loaded into context
  - Tool calls made (and which tools)
  - First-call accuracy (right tool on first try)
  - Total API tokens consumed
  - Final answer (truncated)
"""

import asyncio
import json
import os
import time
from dotenv import load_dotenv

load_dotenv(".env")

import anthropic
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

TASK = (
    "List the files in /Users/arjunmahendra/mcp-tool-optimizer "
    "and explain how the scoring algorithm works based on the README."
)

# Tools that are the "right" first call for this task
CORRECT_FIRST_TOOLS = {"list_directory", "read_file", "read_text_file"}

MODEL = "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Tool schema helpers
# ---------------------------------------------------------------------------

def mcp_tool_to_anthropic(tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
    }

def schema_tokens(tools: list) -> int:
    return sum(len(json.dumps(mcp_tool_to_anthropic(t))) // 4 for t in tools)


# ---------------------------------------------------------------------------
# Tool fetchers
# ---------------------------------------------------------------------------

async def fetch_full_pool() -> list:
    """Fetch all tools directly from both upstream MCP servers."""
    tools = []
    token = os.environ.get("GITHUB_TOKEN", "")

    fs_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/Users/arjunmahendra"],
    )
    async with stdio_client(fs_params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools += (await s.list_tools()).tools

    gh_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": token, "PATH": os.environ["PATH"]},
    )
    async with stdio_client(gh_params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools += (await s.list_tools()).tools

    return tools


async def fetch_optimized_pool() -> list:
    """Fetch active tools through the mcpforge proxy."""
    async with sse_client("http://localhost:8765/sse") as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return (await s.list_tools()).tools


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

async def execute_tool(name: str, args: dict) -> str:
    """Route a tool call to the right upstream server."""
    token = os.environ.get("GITHUB_TOKEN", "")

    # Filesystem tools
    fs_tools = {
        "read_file", "read_text_file", "read_media_file", "read_multiple_files",
        "write_file", "edit_file", "create_directory", "list_directory",
        "list_directory_with_sizes", "directory_tree", "move_file",
        "get_file_info", "list_allowed_directories", "search_files",
    }
    if name in fs_tools:
        params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/Users/arjunmahendra"],
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                result = await s.call_tool(name, args)
    else:
        params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": token, "PATH": os.environ["PATH"]},
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                result = await s.call_tool(name, args)

    return result.content[0].text if result.content else "(no result)"


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

async def run_task(label: str, tools: list) -> dict:
    client = anthropic.AsyncAnthropic()
    anthropic_tools = [mcp_tool_to_anthropic(t) for t in tools]
    tool_names = [t["name"] for t in anthropic_tools]

    messages = [{"role": "user", "content": TASK}]
    calls_made = []
    total_input_tokens = 0
    total_output_tokens = 0
    t0 = time.perf_counter()

    while True:
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=1024,
            tools=anthropic_tools,
            messages=messages,
        )
        total_input_tokens += resp.usage.input_tokens
        total_output_tokens += resp.usage.output_tokens

        if resp.stop_reason == "end_turn":
            final = next(
                (b.text for b in resp.content if b.type == "text"), "(no text)"
            )
            break

        # Execute tool calls
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                calls_made.append(block.name)
                result_text = await execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text[:4000],
                })

        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": tool_results})

    elapsed = time.perf_counter() - t0
    first_correct = calls_made[0] in CORRECT_FIRST_TOOLS if calls_made else False

    return {
        "label": label,
        "tool_count": len(tools),
        "schema_tokens": schema_tokens(tools),
        "tool_names_available": tool_names,
        "calls_made": calls_made,
        "first_call": calls_made[0] if calls_made else "(none)",
        "first_call_correct": first_correct,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "elapsed_s": round(elapsed, 2),
        "answer": final[:400] + ("…" if len(final) > 400 else ""),
    }


# ---------------------------------------------------------------------------
# Print comparison
# ---------------------------------------------------------------------------

def print_results(full: dict, opt: dict):
    W = 60
    print("\n" + "=" * W)
    print(f"{'METRIC':<30} {'FULL':>12} {'OPTIMIZED':>12}")
    print("-" * W)

    rows = [
        ("Tools available",      full["tool_count"],          opt["tool_count"]),
        ("Schema tokens loaded", full["schema_tokens"],        opt["schema_tokens"]),
        ("Total input tokens",   full["total_input_tokens"],   opt["total_input_tokens"]),
        ("Total output tokens",  full["total_output_tokens"],  opt["total_output_tokens"]),
        ("Total tokens",         full["total_tokens"],         opt["total_tokens"]),
        ("Tool calls made",      len(full["calls_made"]),      len(opt["calls_made"])),
        ("Elapsed (s)",          full["elapsed_s"],            opt["elapsed_s"]),
    ]
    for label, fv, ov in rows:
        saved = ""
        if isinstance(fv, (int, float)) and isinstance(ov, (int, float)) and fv > 0:
            pct = (fv - ov) / fv * 100
            saved = f"  ({pct:+.0f}%)" if pct != 0 else ""
        print(f"  {label:<28} {str(fv):>12} {str(ov) + saved:>12}")

    print("-" * W)
    print(f"  {'First tool called':<28} {full['first_call']:>12} {opt['first_call']:>12}")
    print(f"  {'First call correct':<28} {str(full['first_call_correct']):>12} {str(opt['first_call_correct']):>12}")
    print(f"  {'Tools sequence (full)':<28} {' → '.join(full['calls_made'])}")
    print(f"  {'Tools sequence (opt)':<28} {' → '.join(opt['calls_made'])}")
    print("=" * W)

    print(f"\nFULL answer:\n  {full['answer']}\n")
    print(f"OPTIMIZED answer:\n  {opt['answer']}\n")


async def main():
    print(f"Task: {TASK}\n")
    print("Fetching tool pools...")

    full_tools, opt_tools = await asyncio.gather(
        fetch_full_pool(),
        fetch_optimized_pool(),
    )
    print(f"  Full pool:      {len(full_tools)} tools  ({schema_tokens(full_tools):,} schema tokens)")
    print(f"  Optimized pool: {len(opt_tools)} tools  ({schema_tokens(opt_tools):,} schema tokens)")

    print("\nRunning full pool...")
    full_result = await run_task("FULL", full_tools)

    print("Running optimized pool...")
    opt_result = await run_task("OPTIMIZED", opt_tools)

    print_results(full_result, opt_result)


if __name__ == "__main__":
    asyncio.run(main())
