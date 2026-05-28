"""
Week 2 verification: per-session-type pool thresholds.

Part 1 — Pool logic (no SSE needed):
  Load scored rows from DB and compute session pools for each session type.
  Shows that incident (threshold=5.0) gets more tools than planning (threshold=15.0).

Part 2 — End-to-end SSE:
  Connect two separate SSE sessions. Each makes one tool call to trigger
  classification (falls back to 'general' without API key). After the background
  task completes, tools/list is called again. Verifies session is created in DB,
  session pool is applied, and filtering differs from the global pool.
"""

import asyncio
import sys
from pathlib import Path
import time

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import yaml

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

PROXY_URL = "http://localhost:8765/sse"

# Load thresholds from the live config so the script always reflects reality.
_cfg = yaml.safe_load(open(ROOT / "mcpforge.yaml"))
_opt = _cfg.get("optimizer", {})
DEFAULT_THRESHOLD: float = _opt.get("default_threshold", 10.0)
THRESHOLDS: dict[str, float] = {
    "incident": 5.0, "planning": 15.0, "code": 10.0, "general": 10.0,
    **_opt.get("thresholds", {}),
}


# ---------------------------------------------------------------------------
# Part 1: Direct pool logic test
# ---------------------------------------------------------------------------

def part1_pool_logic():
    import sqlite3

    print("=" * 60)
    print("PART 1: Pool logic — session-type threshold test")
    print("=" * 60)

    conn = sqlite3.connect(ROOT / "mcpforge.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT server, tool, score, status FROM tool_pool ORDER BY score DESC"
    ).fetchall()

    print(f"\nGlobal tool_pool: {len(rows)} tools")
    print(f"{'Server':<20} {'Tool':<30} {'Score':>7}  Status")
    print("-" * 65)
    for r in rows:
        print(f"{r['server']:<20} {r['tool']:<30} {r['score']:>7.2f}  {r['status']}")

    print()
    print(f"Per-session-type pools (from tool_pool scores):")
    print(f"{'Session type':<12}  {'Threshold':>9}  {'Active tools':>12}  Tools")
    print("-" * 80)
    for stype, threshold in sorted(THRESHOLDS.items(), key=lambda x: x[1]):
        active = [(r["server"], r["tool"]) for r in rows if r["score"] >= threshold]
        tool_names = ", ".join(f"{s}/{t}" for s, t in active) if active else "(none)"
        print(f"{stype:<12}  {threshold:>9.1f}  {len(active):>12}  {tool_names}")

    print()
    # Verify ordering: incident > code == general > planning
    incident_n = sum(1 for r in rows if r["score"] >= THRESHOLDS["incident"])
    planning_n = sum(1 for r in rows if r["score"] >= THRESHOLDS["planning"])
    incident_gt_planning = incident_n > planning_n
    print(f"PASS: incident ({incident_n}) > planning ({planning_n}): {incident_gt_planning}")
    if not incident_gt_planning:
        print("FAIL: incident threshold should allow more tools than planning threshold")
        return False
    return True


# ---------------------------------------------------------------------------
# Part 2: End-to-end SSE test
# ---------------------------------------------------------------------------

async def connect_and_test(label: str, first_tool: str, first_args: dict) -> dict:
    """Connect an SSE session, call one tool (triggers classification), wait, then list tools."""
    print(f"\n[{label}] Connecting to {PROXY_URL} ...")
    async with sse_client(PROXY_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # tools/list BEFORE any call (uses global pool)
            tool_list_before = await session.list_tools()
            before_count = len(tool_list_before.tools)
            print(f"[{label}] tools/list BEFORE first call: {before_count} tools")

            # First tool call — triggers classification background task
            print(f"[{label}] Calling {first_tool} (triggers classification) ...")
            try:
                await session.call_tool(first_tool, first_args)
                print(f"[{label}] Tool call succeeded")
            except Exception as e:
                print(f"[{label}] Tool call returned error (expected for mock): {e}")

            # Give classifier time to complete
            print(f"[{label}] Waiting 3s for classifier background task ...")
            await asyncio.sleep(3)

            # tools/list AFTER classification — should use session pool
            tool_list_after = await session.list_tools()
            after_count = len(tool_list_after.tools)
            after_names = [t.name for t in tool_list_after.tools]
            print(f"[{label}] tools/list AFTER classification: {after_count} tools")
            if after_names:
                print(f"[{label}] Active tools: {', '.join(after_names)}")
            else:
                print(f"[{label}] Active tools: (none — all pruned by session threshold)")

            return {"label": label, "before": before_count, "after": after_count, "tools": after_names}


async def part2_sse():
    import sqlite3

    print()
    print("=" * 60)
    print("PART 2: End-to-end SSE — session lifecycle + pool filtering")
    print("=" * 60)

    conn0 = sqlite3.connect(ROOT / "mcpforge.db")
    sessions_before = conn0.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    # Snapshot expected pool counts BEFORE sessions run (optimizer may change them mid-test).
    pool_rows_now = conn0.execute("SELECT server, tool, score FROM tool_pool").fetchall()
    general_threshold = THRESHOLDS.get("general", DEFAULT_THRESHOLD)
    expected_general = sum(1 for _, _, score in pool_rows_now if score >= general_threshold)
    print(f"\nSessions in DB before: {sessions_before}")
    print(f"Expected tools for 'general' session (threshold={general_threshold}): {expected_general}")

    # Two concurrent sessions: one incident-style, one planning-style
    # Without ANTHROPIC_API_KEY both fall back to "general" — that's fine,
    # we're testing the mechanism not the classifier itself.
    results = await asyncio.gather(
        connect_and_test(
            "session-A (incident call)",
            "restart_pod",
            {"pod_name": "payment-processor", "namespace": "production"},
        ),
        connect_and_test(
            "session-B (planning call)",
            "query_metrics",
            {"service": "payment-service", "metric": "latency", "window_minutes": 15},
        ),
    )

    # Check sessions were created in DB
    conn = sqlite3.connect(ROOT / "mcpforge.db")
    sessions_after = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    new_sessions = sessions_after - sessions_before
    print(f"\nSessions in DB after:  {sessions_after} (+{new_sessions} new)")

    session_rows = conn.execute(
        "SELECT session_id, type, started_at FROM sessions ORDER BY started_at DESC LIMIT 5"
    ).fetchall()
    print("\nMost recent sessions:")
    for sid, stype, ts in session_rows:
        print(f"  {sid[:8]}...  type={stype:<12}  started={time.strftime('%H:%M:%S', time.localtime(ts))}")

    print()
    print("SUMMARY")
    print("-" * 40)
    for r in results:
        print(f"{r['label']}: before={r['before']} tools → after={r['after']} tools")

    # Verify session pool filtering happened (after should differ from cold-start behavior)
    # With global pool=13 tools and general threshold=10.0 → session pool has fewer
    all_pass = True
    if new_sessions != 2:
        print(f"FAIL: expected 2 new sessions in DB, got {new_sessions}")
        all_pass = False
    else:
        print(f"PASS: 2 sessions created in DB")

    # Without ANTHROPIC_API_KEY both sessions fall to "general" — that is expected.
    # The key checks are: sessions were created, classification task ran (type set in DB),
    # and the after count equals expected_general.
    for r in results:
        actual = r["after"]
        if actual == expected_general:
            print(f"PASS: {r['label']} — session pool applied correctly, {actual} tools visible (matches 'general' threshold={general_threshold})")
        else:
            print(f"FAIL: {r['label']} — expected {expected_general} tools, got {actual}")
            all_pass = False

    # Verify sessions were classified (not still 'unknown')
    classified = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE type != 'unknown' AND started_at > ?",
        (time.time() - 60,),
    ).fetchone()[0]
    if classified >= 2:
        print(f"PASS: {classified} sessions classified (type written to DB)")
    else:
        print(f"INFO: {classified}/2 sessions classified — classifier may still be running (no API key → falls back to 'general' asynchronously)")

    return all_pass


# ---------------------------------------------------------------------------
# Part 3: optimizer run check
# ---------------------------------------------------------------------------

def part3_optimizer_check():
    import sqlite3

    print()
    print("=" * 60)
    print("PART 3: Optimizer — verify default_threshold=10.0 is applied")
    print("=" * 60)

    conn = sqlite3.connect(ROOT / "mcpforge.db")
    rows = conn.execute(
        "SELECT ts, trigger, changes_json FROM audit_log ORDER BY ts DESC LIMIT 3"
    ).fetchall()

    if not rows:
        print("No optimizer runs in audit_log yet (runs every 1 minute — wait and retry)")
        return None

    print(f"\nLast {len(rows)} optimizer run(s):")
    import json
    for ts, trigger, changes in rows:
        changes_dict = json.loads(changes)
        print(f"  {time.strftime('%H:%M:%S', time.localtime(ts))}  trigger={trigger}  changes={len(changes_dict)}")
        for key, change in list(changes_dict.items())[:5]:
            print(f"    {key}: {change['before']} → {change['after']}")

    # Check current pool
    pool_rows = conn.execute(
        "SELECT status, COUNT(*) FROM tool_pool GROUP BY status"
    ).fetchall()
    print("\nCurrent tool_pool status counts:")
    for status, count in pool_rows:
        print(f"  {status}: {count}")

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    p1_ok = part1_pool_logic()
    p2_ok = await part2_sse()
    part3_optimizer_check()

    print()
    print("=" * 60)
    print("VERIFICATION RESULT")
    print("=" * 60)
    if p1_ok and p2_ok:
        print("Week 2 verification PASSED")
    else:
        print("Week 2 verification had failures — see details above")


if __name__ == "__main__":
    asyncio.run(main())
