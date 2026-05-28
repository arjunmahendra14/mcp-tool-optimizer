import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import scorer, store
from .pool import pool

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def run_optimization(config, trigger: str = "scheduled") -> list[dict]:
    logger.info(f"Optimizer triggered: {trigger}")

    tool_calls = store.get_tool_calls(hours=7 * 24)

    if not tool_calls:
        logger.info("No usage data yet — keeping full pool active")
        return []

    latency_stats = store.get_latency_stats(hours=7 * 24)
    scored = scorer.score_tools(tool_calls, latency_stats)
    threshold = config.optimizer.default_threshold

    before = store.get_tool_pool()
    before_statuses = {(r["server"], r["tool"]): r["status"] for r in before}

    scored_with_status = [
        {**item, "status": "active" if item["score"] >= threshold else "pruned"}
        for item in scored
    ]

    for item in scored_with_status:
        store.upsert_tool_pool(item["server"], item["tool"], item["score"], item["status"])

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

    active_count = sum(1 for s in after_statuses.values() if s == "active")
    pruned_count = sum(1 for s in after_statuses.values() if s == "pruned")
    logger.info(f"Optimized pool: {active_count} active, {pruned_count} pruned")

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
