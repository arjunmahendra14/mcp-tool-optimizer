"""Pure scoring functions — no I/O, no side effects."""

import math
import time
from collections import defaultdict


def recency_decay(hours_since_last_call: float) -> float:
    """Convert hours since last call to a weight in (0, 1]; recent calls score higher."""
    return 1 / math.log(hours_since_last_call + math.e)


LATENCY_CAP_MS = 10_000


def latency_penalty(p99_ms: float) -> float:
    """Convert p99 latency to a penalty divisor; capped so slow-but-useful tools aren't destroyed."""
    return math.log(min(p99_ms, LATENCY_CAP_MS) + 1)


def compute_score(call_count: int, hours_since_last: float, p99_ms: float) -> float:
    """Compute numerical tool score from call frequency, recency, and capped latency."""
    if call_count == 0:
        return 0.0
    return (call_count * recency_decay(hours_since_last)) / latency_penalty(p99_ms)


def compute_hybrid_score(numerical: float, ai_usefulness: float) -> float:
    """Combine numerical score with AI usefulness rating (0.0–1.0 multiplier)."""
    return numerical * max(0.0, min(1.0, ai_usefulness))


def score_tools(
    tool_calls: list[dict],
    latency_stats: dict[tuple[str, str], float] | None = None,
) -> list[dict]:
    """Return scored list of {server, tool, score} sorted descending.

    Uses call_count × recency_decay / latency_penalty. Tools absent from
    latency_stats default to 100ms p99.
    """
    now = time.time()
    if latency_stats is None:
        latency_stats = {}

    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in tool_calls:
        key = (row["server"], row["tool"])
        groups[key].append(float(row["ts"]))

    results = []
    for (server, tool), timestamps in groups.items():
        call_count = len(timestamps)
        hours_since = (now - max(timestamps)) / 3600.0
        p99_ms = latency_stats.get((server, tool), 100.0)
        score = compute_score(call_count, hours_since, p99_ms)
        results.append({"server": server, "tool": tool, "score": round(score, 4)})

    return sorted(results, key=lambda x: x["score"], reverse=True)
