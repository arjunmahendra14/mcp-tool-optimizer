import json
import sqlite3
import threading
import time
from collections import defaultdict
from typing import Optional

_db_path: str = "mcpforge.db"
_lock = threading.Lock()


def init_db(path: str) -> None:
    global _db_path
    _db_path = path
    with _connect() as conn:
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

            CREATE TABLE IF NOT EXISTS tool_pool (
                server TEXT NOT NULL,
                tool TEXT NOT NULL,
                score REAL DEFAULT 0.0,
                status TEXT DEFAULT 'active',
                last_updated REAL,
                PRIMARY KEY (server, tool)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                trigger TEXT NOT NULL,
                changes_json TEXT NOT NULL,
                pool_snapshot_json TEXT NOT NULL
            );
        """)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def log_tool_call(
    session_id: str,
    server: str,
    tool: str,
    latency_ms: float,
    session_type: str = "unknown",
) -> None:
    """Insert a tool call record with timing and session context."""
    with _lock:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO tool_calls (session_id, server, tool, latency_ms, ts, session_type)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, server, tool, latency_ms, time.time(), session_type),
            )


def create_session(session_id: str) -> None:
    """Insert a new session record with type='unknown'."""
    with _lock:
        with _connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?)",
                (session_id, time.time()),
            )


def update_session_type(session_id: str, session_type: str) -> None:
    """Update the type field for an existing session."""
    with _lock:
        with _connect() as conn:
            conn.execute(
                "UPDATE sessions SET type = ? WHERE session_id = ?",
                (session_type, session_id),
            )


def get_session(session_id: str) -> Optional[dict]:
    """Return a session record by ID."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def get_tool_calls(hours: int = 24) -> list[dict]:
    cutoff = time.time() - hours * 3600
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tool_calls WHERE ts >= ? ORDER BY ts DESC",
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_latency_stats(hours: int = 7 * 24) -> dict[tuple[str, str], float]:
    """Return p99 latency in ms per (server, tool) computed from recent tool calls."""
    cutoff = time.time() - hours * 3600
    with _connect() as conn:
        rows = conn.execute(
            "SELECT server, tool, latency_ms FROM tool_calls WHERE ts >= ?",
            (cutoff,),
        ).fetchall()

    latencies: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        latencies[(row["server"], row["tool"])].append(row["latency_ms"])

    result: dict[tuple[str, str], float] = {}
    for key, values in latencies.items():
        values.sort()
        p99_idx = min(int(len(values) * 0.99), len(values) - 1)
        result[key] = values[p99_idx]

    return result


def upsert_tool_pool(server: str, tool: str, score: float, status: str) -> None:
    with _lock:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_pool (server, tool, score, status, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(server, tool) DO UPDATE SET
                    score=excluded.score,
                    status=excluded.status,
                    last_updated=excluded.last_updated
                """,
                (server, tool, score, status, time.time()),
            )


def get_tool_pool() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT server, tool, score, status FROM tool_pool ORDER BY score DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_active_tools() -> set[tuple[str, str]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT server, tool FROM tool_pool WHERE status = 'active'"
        ).fetchall()
    return {(row["server"], row["tool"]) for row in rows}


def restore_tool_pool(entries: list[dict]) -> None:
    with _lock:
        with _connect() as conn:
            conn.execute("DELETE FROM tool_pool")
            for e in entries:
                conn.execute(
                    "INSERT INTO tool_pool (server, tool, score, status, last_updated) VALUES (?, ?, ?, ?, ?)",
                    (e["server"], e["tool"], e["score"], e["status"], time.time()),
                )


def write_audit_log(trigger: str, changes: dict, pool_snapshot: list[dict]) -> None:
    with _lock:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO audit_log (ts, trigger, changes_json, pool_snapshot_json) VALUES (?, ?, ?, ?)",
                (
                    time.time(),
                    trigger,
                    json.dumps(changes),
                    json.dumps(pool_snapshot),
                ),
            )


def get_audit_log(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_audit_entry(run_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE id = ?", (run_id,)
        ).fetchone()
    return dict(row) if row else None
