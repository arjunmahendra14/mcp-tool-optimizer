import asyncio
import json
import logging
import sqlite3
import threading
import time
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

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
                session_type TEXT DEFAULT 'unknown',
                success INTEGER DEFAULT 1,
                result_size INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                type TEXT DEFAULT 'unknown',
                started_at REAL NOT NULL,
                message_count INTEGER DEFAULT 0,
                outcome TEXT DEFAULT 'unknown',
                outcome_confidence REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS tool_pool (
                server TEXT NOT NULL,
                tool TEXT NOT NULL,
                score REAL DEFAULT 0.0,
                status TEXT DEFAULT 'active',
                last_updated REAL,
                reserve_alpha REAL DEFAULT 1.0,
                reserve_beta REAL DEFAULT 1.0,
                last_reexposed_at REAL,
                schema_tokens INTEGER DEFAULT 1,
                PRIMARY KEY (server, tool)
            );

            CREATE TABLE IF NOT EXISTS tool_embeddings (
                server TEXT NOT NULL,
                tool TEXT NOT NULL,
                embedding_text TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                embedded_at REAL NOT NULL,
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
        # Migrate existing databases
        migrations = [
            ("tool_calls", "success", "INTEGER DEFAULT 1"),
            ("tool_calls", "result_size", "INTEGER DEFAULT 0"),
            ("sessions", "outcome", "TEXT DEFAULT 'unknown'"),
            ("sessions", "outcome_confidence", "REAL DEFAULT 0.0"),
            ("tool_pool", "reserve_alpha", "REAL DEFAULT 1.0"),
            ("tool_pool", "reserve_beta", "REAL DEFAULT 1.0"),
            ("tool_pool", "last_reexposed_at", "REAL"),
            ("tool_pool", "schema_tokens", "INTEGER DEFAULT 1"),
            ("tool_calls", "pool_timeout", "INTEGER DEFAULT 0"),
        ]
        for table, col, definition in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            except Exception:
                pass
        # Migrate legacy 'pruned' status to 'reserve'
        conn.execute("UPDATE tool_pool SET status = 'reserve' WHERE status = 'pruned'")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _log_tool_call_sync(
    session_id: str, server: str, tool: str, latency_ms: float,
    session_type: str, success: bool, result_size: int, pool_timeout: bool,
) -> None:
    with _lock:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO tool_calls"
                " (session_id, server, tool, latency_ms, ts, session_type, success, result_size, pool_timeout)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, server, tool, latency_ms, time.time(), session_type,
                 1 if success else 0, result_size, 1 if pool_timeout else 0),
            )


def log_tool_call(
    session_id: str,
    server: str,
    tool: str,
    latency_ms: float,
    session_type: str = "unknown",
    success: bool = True,
    result_size: int = 0,
    pool_timeout: bool = False,
) -> None:
    """Insert a tool call record without blocking the asyncio event loop.

    pool_timeout=True marks calls that failed waiting for a pool connection,
    not because the tool itself failed. These are excluded from scoring so
    pool contention doesn't corrupt the learning signal.
    """
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            None, _log_tool_call_sync,
            session_id, server, tool, latency_ms, session_type, success, result_size, pool_timeout,
        )
        future.add_done_callback(
            lambda f: logger.warning(f"log_tool_call failed: {f.exception()}")
            if not f.cancelled() and f.exception() else None
        )
    except RuntimeError:
        _log_tool_call_sync(session_id, server, tool, latency_ms, session_type, success, result_size, pool_timeout)


def create_session(session_id: str) -> None:
    """Insert a new session record with type='unknown'."""
    with _lock:
        with _connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?)",
                (session_id, time.time()),
            )


def update_session_outcome(
    session_id: str,
    outcome: str,
    confidence: float = 0.0,
) -> None:
    """Record heuristic session outcome: completed, abandoned, error, or unknown."""
    with _lock:
        with _connect() as conn:
            conn.execute(
                "UPDATE sessions SET outcome = ?, outcome_confidence = ? WHERE session_id = ?",
                (outcome, confidence, session_id),
            )


def get_session_calls(session_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tool_calls WHERE session_id = ? ORDER BY ts",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


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


def get_tool_calls(hours: int = 24, exclude_pool_timeout: bool = False) -> list[dict]:
    cutoff = time.time() - hours * 3600
    pt_clause = " AND pool_timeout = 0" if exclude_pool_timeout else ""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM tool_calls WHERE ts >= ?{pt_clause} ORDER BY ts DESC",
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_latency_stats(hours: int = 7 * 24) -> dict[tuple[str, str], float]:
    """Return p99 latency in ms per (server, tool) computed from recent tool calls.

    Pool-timeout calls are excluded — their latency reflects queue wait time,
    not actual tool execution time.
    """
    cutoff = time.time() - hours * 3600
    with _connect() as conn:
        rows = conn.execute(
            "SELECT server, tool, latency_ms FROM tool_calls"
            " WHERE ts >= ? AND pool_timeout = 0",
            (cutoff,),
        ).fetchall()

    latencies: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        latencies[(row["server"], row["tool"])].append(row["latency_ms"])

    result: dict[tuple[str, str], float] = {}
    for key, values in latencies.items():
        values.sort()
        p99_idx = min(int((len(values) - 1) * 0.99), len(values) - 1)
        result[key] = values[p99_idx]

    return result


def get_utility_stats(hours: int = 7 * 24) -> dict[tuple[str, str], dict]:
    """Return per-(server, tool) utility stats: success_rate, avg_result_size, follow_on_rate."""
    cutoff = time.time() - hours * 3600
    with _connect() as conn:
        rows = conn.execute(
            "SELECT server, tool, success, result_size, ts, session_id"
            " FROM tool_calls WHERE ts >= ?",
            (cutoff,),
        ).fetchall()

    if not rows:
        return {}

    from collections import defaultdict
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        groups[(row["server"], row["tool"])].append(dict(row))

    # Build a lookup: session_id -> sorted list of (ts, server, tool)
    session_calls: dict[str, list] = defaultdict(list)
    for (server, tool), calls in groups.items():
        for c in calls:
            session_calls[c["session_id"]].append((c["ts"], server, tool))
    for sid in session_calls:
        session_calls[sid].sort()

    result = {}
    for (server, tool), calls in groups.items():
        total = len(calls)
        success_rate = sum(c["success"] for c in calls) / total
        avg_result_size = sum(c["result_size"] for c in calls) / total

        # Follow-on: did another tool call happen in the same session within 60s?
        follow_ons = 0
        for c in calls:
            sid = c["session_id"]
            ts = c["ts"]
            others = session_calls[sid]
            # any call on a different tool within 60s after this one
            for other_ts, other_server, other_tool in others:
                if other_ts <= ts:
                    continue
                if other_ts - ts > 60:
                    break
                if (other_server, other_tool) != (server, tool):
                    follow_ons += 1
                    break

        result[(server, tool)] = {
            "success_rate": success_rate,
            "avg_result_size": avg_result_size,
            "follow_on_rate": follow_ons / total,
        }

    return result


def get_aggregated_stats(hours: int = 7 * 24) -> list[dict]:
    """Return compacted per-tool substrate: recency-weighted calls, success rate,
    avg result size, follow-on rate, last-used, session-type distribution."""
    import math as _math

    cutoff = time.time() - hours * 3600
    now = time.time()

    with _connect() as conn:
        rows = conn.execute(
            "SELECT server, tool, latency_ms, ts, success, result_size, session_id, session_type"
            " FROM tool_calls WHERE ts >= ? AND pool_timeout = 0 ORDER BY ts",
            (cutoff,),
        ).fetchall()

    if not rows:
        return []

    from collections import defaultdict
    groups: dict[tuple[str, str], list] = defaultdict(list)
    session_calls: dict[str, list] = defaultdict(list)
    for row in rows:
        key = (row["server"], row["tool"])
        groups[key].append(dict(row))
        session_calls[row["session_id"]].append((row["ts"], row["server"], row["tool"]))
    for sid in session_calls:
        session_calls[sid].sort()

    result = []
    for (server, tool), calls in groups.items():
        total = len(calls)
        recency_weighted = sum(
            1 / _math.log((now - c["ts"]) / 3600 + _math.e)
            for c in calls
        )
        success_rate = sum(c["success"] for c in calls) / total
        avg_result_size = sum(c["result_size"] for c in calls) / total
        last_used_h = (now - max(c["ts"] for c in calls)) / 3600

        # Follow-on rate
        follow_ons = 0
        for c in calls:
            for other_ts, other_srv, other_tool in session_calls[c["session_id"]]:
                if other_ts <= c["ts"]:
                    continue
                if other_ts - c["ts"] > 60:
                    break
                if (other_srv, other_tool) != (server, tool):
                    follow_ons += 1
                    break

        # Session-type distribution
        type_counts: dict[str, int] = defaultdict(int)
        for c in calls:
            type_counts[c["session_type"]] += 1
        type_dist = {k: round(v / total, 2) for k, v in type_counts.items()}

        result.append({
            "server": server,
            "tool": tool,
            "recency_weighted_calls": round(recency_weighted, 3),
            "total_calls": total,
            "success_rate": round(success_rate, 3),
            "avg_result_size": round(avg_result_size),
            "follow_on_rate": round(follow_ons / total, 3),
            "last_used_hours_ago": round(last_used_h, 1),
            "session_type_dist": type_dist,
        })

    return sorted(result, key=lambda x: x["recency_weighted_calls"], reverse=True)


def get_cooccurrence(hours: int = 7 * 24) -> list[dict]:
    """Return tool pairs that appeared in the same session, with session count."""
    cutoff = time.time() - hours * 3600
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                a.server || '/' || a.tool AS tool_a,
                b.server || '/' || b.tool AS tool_b,
                COUNT(DISTINCT a.session_id) AS sessions
            FROM tool_calls a
            JOIN tool_calls b
                ON a.session_id = b.session_id
                AND (a.server || a.tool) < (b.server || b.tool)
            WHERE a.ts >= ? AND b.ts >= ?
            GROUP BY tool_a, tool_b
            ORDER BY sessions DESC
            """,
            (cutoff, cutoff),
        ).fetchall()
    return [dict(row) for row in rows]


def get_session_outcomes(hours: int = 7 * 24) -> dict:
    """Return session outcome distribution and recent session summaries."""
    cutoff = time.time() - hours * 3600
    with _connect() as conn:
        rows = conn.execute(
            "SELECT outcome, COUNT(*) as count FROM sessions"
            " WHERE started_at >= ? GROUP BY outcome",
            (cutoff,),
        ).fetchall()
    return {row["outcome"]: row["count"] for row in rows}


def get_reserve_pool() -> list[dict]:
    """Return reserve tools with their Thompson sampling parameters."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT server, tool, score, reserve_alpha, reserve_beta, last_reexposed_at"
            " FROM tool_pool WHERE status = 'reserve' ORDER BY last_reexposed_at ASC NULLS FIRST"
        ).fetchall()
    return [dict(row) for row in rows]


def update_reserve_exposure(server: str, tool: str, was_used: bool) -> None:
    """Update Beta distribution params after a reserve tool re-exposure cycle."""
    with _lock:
        with _connect() as conn:
            if was_used:
                conn.execute(
                    "UPDATE tool_pool SET reserve_alpha = reserve_alpha + 1"
                    " WHERE server = ? AND tool = ?",
                    (server, tool),
                )
            else:
                conn.execute(
                    "UPDATE tool_pool SET reserve_beta = reserve_beta + 1"
                    " WHERE server = ? AND tool = ?",
                    (server, tool),
                )


def upsert_tool_pool(
    server: str,
    tool: str,
    score: float,
    status: str,
    mark_reexposed: bool = False,
) -> None:
    """status must be one of: active, reserve, excluded."""
    assert status in ("active", "reserve", "excluded"), f"Invalid status: {status}"
    with _lock:
        with _connect() as conn:
            reexposed_val = time.time() if mark_reexposed else None
            conn.execute(
                """
                INSERT INTO tool_pool (server, tool, score, status, last_updated, last_reexposed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(server, tool) DO UPDATE SET
                    score=excluded.score,
                    status=excluded.status,
                    last_updated=excluded.last_updated,
                    last_reexposed_at=COALESCE(excluded.last_reexposed_at, tool_pool.last_reexposed_at)
                """,
                (server, tool, score, status, time.time(), reexposed_val),
            )


def upsert_tool_schema_tokens(server: str, tool: str, tokens: int) -> None:
    """Store the token cost of a tool's schema. Creates the row if it doesn't exist."""
    with _lock:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO tool_pool (server, tool, schema_tokens, last_updated)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(server, tool) DO UPDATE SET schema_tokens=excluded.schema_tokens",
                (server, tool, tokens, time.time()),
            )


def get_tool_pool() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT server, tool, score, status,"
            " COALESCE(schema_tokens, 1) as schema_tokens,"
            " COALESCE(reserve_alpha, 1.0) as reserve_alpha,"
            " COALESCE(reserve_beta, 1.0) as reserve_beta,"
            " last_reexposed_at"
            " FROM tool_pool ORDER BY score DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_active_tools() -> set[tuple[str, str]]:
    """Active tools are shown in tools/list. Reserve and excluded are hidden."""
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
                    "INSERT INTO tool_pool"
                    " (server, tool, score, status, last_updated,"
                    " schema_tokens, reserve_alpha, reserve_beta, last_reexposed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        e["server"], e["tool"], e["score"], e["status"], time.time(),
                        e.get("schema_tokens", 1),
                        e.get("reserve_alpha", 1.0),
                        e.get("reserve_beta", 1.0),
                        e.get("last_reexposed_at"),
                    ),
                )


def upsert_tool_embedding(
    server: str,
    tool: str,
    embedding_text: str,
    embedding: list[float],
) -> None:
    """Store a tool's embedding vector. Overwrites if description text changed."""
    with _lock:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_embeddings (server, tool, embedding_text, embedding_json, embedded_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(server, tool) DO UPDATE SET
                    embedding_text=excluded.embedding_text,
                    embedding_json=excluded.embedding_json,
                    embedded_at=excluded.embedded_at
                WHERE excluded.embedding_text != tool_embeddings.embedding_text
                """,
                (server, tool, embedding_text, json.dumps(embedding), time.time()),
            )


def get_tool_embeddings() -> dict[tuple[str, str], list[float]]:
    """Return all stored tool embeddings keyed by (server, tool)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT server, tool, embedding_json FROM tool_embeddings"
        ).fetchall()
    return {
        (row["server"], row["tool"]): json.loads(row["embedding_json"])
        for row in rows
    }


def get_embedded_tool_texts() -> dict[tuple[str, str], str]:
    """Return the canonical text used to embed each tool (for change detection)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT server, tool, embedding_text FROM tool_embeddings"
        ).fetchall()
    return {(row["server"], row["tool"]): row["embedding_text"] for row in rows}


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
