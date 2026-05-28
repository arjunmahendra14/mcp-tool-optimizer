"""
Insert fake tool_call rows directly into mcpforge.db so the optimizer has
data to score. HOT tools (datadog, slack, k8s, pagerduty) get many calls;
COLD tools (github, sentry, confluence, jira, linear, notion) get none.
"""

import random
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = str(Path(__file__).parent.parent / "mcpforge.db")

# (server, tool, call_count)
HOT = [
    ("datadog-mcp",    "query_metrics",      20),
    ("datadog-mcp",    "search_logs",        15),
    ("datadog-mcp",    "list_monitors",      12),
    ("datadog-mcp",    "get_dashboard",       8),
    ("datadog-mcp",    "silence_monitor",     6),
    ("slack-mcp",      "send_message",       18),
    ("slack-mcp",      "post_to_channel",    10),
    ("slack-mcp",      "create_thread",       7),
    ("kubernetes-mcp", "get_pod_logs",       14),
    ("kubernetes-mcp", "restart_pod",        10),
    ("kubernetes-mcp", "scale_deployment",    8),
    ("pagerduty-mcp",  "escalate_incident",   9),
    ("pagerduty-mcp",  "acknowledge_alert",   7),
    ("pagerduty-mcp",  "get_oncall_schedule", 5),
]

COLD = [
    ("github-mcp",     "create_issue"),
    ("github-mcp",     "list_issues"),
    ("sentry-mcp",     "search_events"),
    ("sentry-mcp",     "resolve_issue"),
    ("confluence-mcp", "search_pages"),
    ("confluence-mcp", "get_page"),
    ("jira-mcp",       "create_ticket"),
    ("jira-mcp",       "search_tickets"),
    ("linear-mcp",     "list_projects"),
    ("notion-mcp",     "query_database"),
]


def seed(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)

    # Ensure tables exist (in case mcpforge hasn't started yet)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tool_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            server TEXT NOT NULL,
            tool TEXT NOT NULL,
            latency_ms REAL NOT NULL,
            ts REAL NOT NULL,
            session_type TEXT DEFAULT 'unknown'
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            type TEXT DEFAULT 'unknown',
            started_at REAL NOT NULL,
            message_count INTEGER DEFAULT 0
        );
    """)

    now = time.time()
    total = 0

    for server, tool, count in HOT:
        session_id = str(uuid.uuid4())
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, type, started_at) VALUES (?, 'incident', ?)",
            (session_id, now - 3600),
        )
        for i in range(count):
            ts = now - random.uniform(0, 3600)
            latency = random.uniform(50, 400)
            conn.execute(
                "INSERT INTO tool_calls (session_id, server, tool, latency_ms, ts, session_type)"
                " VALUES (?, ?, ?, ?, ?, 'incident')",
                (session_id, server, tool, latency, ts),
            )
            total += 1

    conn.commit()
    conn.close()

    print(f"Inserted {total} tool_call rows into {db_path}")
    print(f"HOT:  {[f'{s}/{t}({c})' for s,t,c in HOT]}")
    print(f"COLD: {[f'{s}/{t}' for s,t in COLD]} — 0 calls each")
    print()
    print("Wait up to 1 minute for the optimizer to run, then check:")
    print("  .venv/bin/mcpforge scores")


if __name__ == "__main__":
    seed()
