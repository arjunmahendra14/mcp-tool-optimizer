import json
import logging
import os
import random

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import scorer, store
from .pool import pool

logger = logging.getLogger(__name__)

_AI_SYSTEM = """\
You are the decision layer for an MCP tool pool optimizer. You receive a substrate of \
aggregated telemetry — not raw events — and decide the status of each tool.

Three statuses:
  active   — shown in tools/list every session
  reserve  — set aside, not shown, eligible to return
  excluded — confirmed useless (duplicate, always fails, zero value)

For each tool provide: server, tool, status, reason (one sentence).

Signals to weigh:
- recency_weighted_calls: higher = more recently and frequently used
- success_rate: fraction of calls that returned content without error
- follow_on_rate: fraction of calls followed by another tool within 60s (results were used)
- avg_result_size: bytes returned (more = more substantive)
- last_used_hours_ago: time since last call
- schema_tokens: token cost of this tool's schema in the context window (lower = cheaper to keep)
- utility_per_token: recency_weighted_calls / schema_tokens — the primary efficiency signal
- session_type_dist: which session types use this tool
- co_occurrence: which tools this one appears alongside (load-bearing tools share workflows)
- outcome_dist: session outcomes observed (completed/abandoned/error/unknown)
- latency: slow tools can still be active if follow_on_rate is high

Token budget context: the active pool has a token budget. Prefer keeping high utility_per_token \
tools active. A rarely-used tool with a large schema is a strong reserve candidate even if its \
absolute call count is moderate.

Reserve tools currently being re-exposed (from bandit sampling) should be evaluated \
on whether they were used this cycle. Update their status accordingly.

Protect tools called in the last 24h regardless of score — do not move to reserve mid-use.

Return ONLY valid JSON:
{"decisions": [{"server": "...", "tool": "...", "status": "active|reserve|excluded", "reason": "..."}]}
"""


def _thompson_sample_reserve(
    reserve_tools: list[dict],
    last_reexposed: dict[tuple[str, str], float],
) -> tuple[str, str] | None:
    """Pick one reserve tool to re-expose this cycle using Thompson sampling.

    Each tool has a Beta(alpha, beta) distribution. We sample from each and
    surface the tool with the highest draw. Tools never re-exposed get the
    uninformative prior Beta(1, 1), meaning uniform [0,1] — high uncertainty,
    high exploration probability.
    """
    if not reserve_tools:
        return None

    best_tool = None
    best_sample = -1.0

    for t in reserve_tools:
        alpha = t.get("reserve_alpha", 1.0)
        beta = t.get("reserve_beta", 1.0)
        sample = random.betavariate(alpha, beta)
        if sample > best_sample:
            best_sample = sample
            best_tool = (t["server"], t["tool"])

    return best_tool


async def _ai_decide_pool(
    substrate: dict,
) -> list[dict]:
    """Call Claude Haiku with the full substrate. Returns per-tool status decisions."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)

        user_content = json.dumps(substrate, indent=2)

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=[{"type": "text", "text": _AI_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
        )

        text = next((b.text for b in response.content if b.type == "text"), "{}")
        data = json.loads(text)
        decisions = data.get("decisions", [])
        logger.info(f"AI pool decisions: {len(decisions)} tools decided")
        for d in decisions:
            logger.debug(f"  {d['server']}/{d['tool']} → {d['status']}: {d.get('reason', '')}")
        return decisions

    except Exception as e:
        logger.warning(f"AI pool decisioning failed, falling back to numerical: {e}")
        return []


_scheduler: AsyncIOScheduler | None = None

# Track which tool was re-exposed last cycle so we can update its Beta params
_last_reexposed: tuple[str, str] | None = None


async def run_optimization(config, trigger: str = "scheduled") -> list[dict]:
    global _last_reexposed
    logger.info(f"Optimizer triggered: {trigger}")

    # --- Aggregation substrate (deterministic compaction) ---
    agg_stats = store.get_aggregated_stats(hours=7 * 24)
    if not agg_stats:
        logger.info("No usage data yet — keeping full pool active")
        return []

    cooccurrence = store.get_cooccurrence(hours=7 * 24)
    outcome_dist = store.get_session_outcomes(hours=7 * 24)
    reserve_tools = store.get_reserve_pool()
    latency_stats = store.get_latency_stats(hours=7 * 24)

    # --- Thompson sampling: pick one reserve tool to re-expose ---
    reexpose_tool = _thompson_sample_reserve(reserve_tools, {})
    if reexpose_tool:
        logger.info(f"Thompson sampling: re-exposing {reexpose_tool[0]}/{reexpose_tool[1]}")

    # --- Update Beta params for previously re-exposed tool ---
    if _last_reexposed:
        srv, tool = _last_reexposed
        reexposed_row = next(
            (t for t in reserve_tools if t["server"] == srv and t["tool"] == tool), None
        )
        reexposed_at = reexposed_row.get("last_reexposed_at") if reexposed_row else None
        if reexposed_at:
            recent_calls = store.get_tool_calls(hours=7 * 24, exclude_pool_timeout=True)
            was_used = any(
                c["server"] == srv and c["tool"] == tool and c["ts"] > reexposed_at
                for c in recent_calls
            )
        else:
            was_used = False
        store.update_reserve_exposure(srv, tool, was_used)
        logger.debug(f"Reserve feedback: {srv}/{tool} was_used={was_used} (since reexposed_at={reexposed_at})")

    _last_reexposed = reexpose_tool

    # --- Numerical scores (substrate, not the final decision) ---
    tool_calls = store.get_tool_calls(hours=7 * 24, exclude_pool_timeout=True)
    numerical_scores = scorer.score_tools(tool_calls, latency_stats)
    score_map = {(s["server"], s["tool"]): s["score"] for s in numerical_scores}

    # Pull schema token counts
    pool_rows = store.get_tool_pool()
    token_map = {(r["server"], r["tool"]): r.get("schema_tokens", 1) for r in pool_rows}

    # Merge numerical scores and token costs into agg_stats
    for s in agg_stats:
        key = (s["server"], s["tool"])
        tokens = token_map.get(key, 1)
        score = round(score_map.get(key, 0.0), 4)
        s["numerical_score"] = score
        s["schema_tokens"] = tokens
        s["utility_per_token"] = round(score / tokens, 6) if tokens > 0 else 0.0

    # Mark 24h-protected tools (called recently — must not be moved to reserve)
    protected = {
        (s["server"], s["tool"])
        for s in agg_stats
        if s["last_used_hours_ago"] < 24
    }

    # Build substrate for AI
    substrate = {
        "token_budget": config.optimizer.token_budget,
        "active_tools": agg_stats,
        "reserve_tools": [
            {
                "server": t["server"],
                "tool": t["tool"],
                "reserve_alpha": t.get("reserve_alpha", 1.0),
                "reserve_beta": t.get("reserve_beta", 1.0),
                "last_used_score": score_map.get((t["server"], t["tool"]), 0.0),
                "schema_tokens": token_map.get((t["server"], t["tool"]), 1),
                "reexposed_this_cycle": reexpose_tool == (t["server"], t["tool"]),
            }
            for t in reserve_tools
        ],
        "cooccurrence": cooccurrence[:20],  # top 20 pairs
        "session_outcome_dist": outcome_dist,
        "protected_24h": [f"{s}/{t}" for s, t in protected],
    }

    # --- AI pool decisions ---
    decisions = await _ai_decide_pool(substrate)

    before = store.get_tool_pool()
    before_statuses = {(r["server"], r["tool"]): r["status"] for r in before}

    if decisions:
        # Apply AI decisions, respecting 24h protection
        scored_with_status = []
        decision_map = {(d["server"], d["tool"]): d["status"] for d in decisions}

        for s in agg_stats:
            key = (s["server"], s["tool"])
            ai_status = decision_map.get(key, "active")
            # Override: never move a recently-used tool to reserve/excluded
            if key in protected and ai_status != "active":
                ai_status = "active"
                logger.debug(f"Protected {key[0]}/{key[1]} from demotion (used <24h)")
            scored_with_status.append({
                "server": s["server"],
                "tool": s["tool"],
                "score": s["numerical_score"],
                "status": ai_status,
            })

        # Re-exposed tool temporarily set active regardless of AI decision
        if reexpose_tool:
            for item in scored_with_status:
                if (item["server"], item["tool"]) == reexpose_tool:
                    item["status"] = "active"
                    break
            else:
                # Tool only in reserve pool, not in agg_stats yet
                scored_with_status.append({
                    "server": reexpose_tool[0],
                    "tool": reexpose_tool[1],
                    "score": 0.0,
                    "status": "active",
                })

        logger.info("Pool decisions: AI-driven with 24h protection")

    else:
        # Fallback: token-budget selection — maximize utility/token within budget.
        # Protected tools (used <24h) are always active regardless of budget.
        budget = config.optimizer.token_budget
        tokens_used = 0
        scored_with_status = []

        protected_stats = [s for s in agg_stats if (s["server"], s["tool"]) in protected]
        unprotected_stats = [s for s in agg_stats if (s["server"], s["tool"]) not in protected]
        unprotected_stats.sort(key=lambda s: s["utility_per_token"], reverse=True)

        for s in protected_stats:
            tokens_used += s["schema_tokens"]
            scored_with_status.append({
                "server": s["server"], "tool": s["tool"],
                "score": s["numerical_score"], "status": "active",
            })

        if tokens_used > budget:
            logger.warning(
                f"Token budget exceeded by protected tools alone: "
                f"{tokens_used}/{budget} tokens — all unprotected tools will go to reserve."
            )

        for s in unprotected_stats:
            fits = tokens_used + s["schema_tokens"] <= budget
            scored_with_status.append({
                "server": s["server"], "tool": s["tool"],
                "score": s["numerical_score"],
                "status": "active" if fits else "reserve",
            })
            if fits:
                tokens_used += s["schema_tokens"]

        logger.info(
            f"Pool decisions: token-budget fallback — {tokens_used}/{budget} tokens used"
        )

    # Handle discovered-but-never-called tools (score=0, no usage signal).
    # Preserve 'excluded' status — don't silently resurrect confirmed-useless tools.
    scored_keys = {(s["server"], s["tool"]) for s in scored_with_status}
    for r in pool_rows:
        key = (r["server"], r["tool"])
        if key not in scored_keys:
            keep_status = "excluded" if r["status"] == "excluded" else "reserve"
            scored_with_status.append({
                "server": r["server"], "tool": r["tool"],
                "score": 0.0, "status": keep_status,
            })

    for item in scored_with_status:
        is_reexpose = reexpose_tool == (item["server"], item["tool"])
        store.upsert_tool_pool(
            item["server"], item["tool"], item["score"], item["status"],
            mark_reexposed=is_reexpose,
        )

    pool.update(scored_with_status)

    after = store.get_tool_pool()
    after_statuses = {(r["server"], r["tool"]): r["status"] for r in after}

    changes = {}
    for key in set(before_statuses) | set(after_statuses):
        b = before_statuses.get(key, "absent")
        a = after_statuses.get(key, "absent")
        if b != a:
            changes[f"{key[0]}__{key[1]}"] = {"before": b, "after": a}

    store.write_audit_log(trigger, changes, after)

    active_c = sum(1 for s in after_statuses.values() if s == "active")
    reserve_c = sum(1 for s in after_statuses.values() if s == "reserve")
    excluded_c = sum(1 for s in after_statuses.values() if s == "excluded")
    logger.info(f"Pool: {active_c} active, {reserve_c} reserve, {excluded_c} excluded")

    return scored_with_status


def start_scheduler(config) -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_optimization,
        "interval",
        minutes=config.optimizer.interval_minutes,
        args=[config, "scheduled"],
        id="optimizer",
    )
    _scheduler.start()
    logger.info(f"Optimizer scheduled every {config.optimizer.interval_minutes} minutes")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
