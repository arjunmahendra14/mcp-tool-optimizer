"""In-memory tool pools — global pool and per-session scoped pools."""

import logging

from . import store

logger = logging.getLogger(__name__)


class SessionPool:
    """Active tool pool scoped to a single MCP session.

    Tools visible to this session = global active pool + semantic boost.
    Semantic boost promotes reserve tools that are relevant to this session's
    task — they're surfaced without changing the global pool.
    """

    def __init__(
        self,
        active: set[tuple[str, str]],
        semantic_boost: set[tuple[str, str]] | None = None,
        cold_start: bool = False,
    ) -> None:
        self._active = active
        self._semantic_boost = semantic_boost or set()
        self._cold_start = cold_start

    def is_active(self, server: str, tool: str) -> bool:
        if self._cold_start:
            return True
        return (server, tool) in self._active or (server, tool) in self._semantic_boost

    @property
    def size(self) -> int:
        return len(self._active | self._semantic_boost)

    @property
    def boosted(self) -> set[tuple[str, str]]:
        """Reserve tools promoted into this session by semantic relevance."""
        return self._semantic_boost - self._active


class ToolPool:
    """Global tool pool loaded from SQLite and updated by the optimizer."""

    def __init__(self) -> None:
        self._active: set[tuple[str, str]] = set()
        self._cold_start = True

    def load_from_db(self) -> None:
        """Populate the global pool from the tool_pool table."""
        active = store.get_active_tools()
        if active:
            self._active = active
            self._cold_start = False
            logger.info(f"Loaded {len(self._active)} active tools from DB")
        else:
            self._cold_start = True
            logger.info("Tool pool is empty — cold start mode, all tools are active")

    def is_active(self, server: str, tool: str) -> bool:
        """Return True if the tool is in the global active pool."""
        if self._cold_start:
            return True
        return (server, tool) in self._active

    def update(self, scored_tools: list[dict]) -> None:
        """Replace the global pool with optimizer results.

        Guard: if the optimizer produces zero active tools (over-aggressive pruning
        with sparse data), keep all non-excluded tools active rather than silently
        blocking every tools/list response.
        """
        active = {
            (t["server"], t["tool"])
            for t in scored_tools
            if t["status"] == "active"
        }
        if not active and scored_tools:
            # Fall back to all non-excluded tools so the proxy stays functional
            active = {
                (t["server"], t["tool"])
                for t in scored_tools
                if t["status"] != "excluded"
            }
            logger.warning(
                f"Optimizer produced 0 active tools — keeping {len(active)} reserve tools visible"
            )
        self._active = active
        self._cold_start = False
        logger.info(f"Pool updated: {len(self._active)} active tools")

    def compute_session_pool(
        self,
        session_type: str,
        scored_rows: list[dict],
        thresholds: dict[str, float],
        default_threshold: float,
    ) -> SessionPool:
        """Build a session-scoped pool from the global active set.

        The global pool already reflects AI decisions (active/reserve/excluded).
        Session-type thresholds act as a secondary filter within the active set
        only — they cannot promote reserve or excluded tools.
        """
        if self._cold_start:
            return SessionPool(set(), cold_start=True)

        threshold = thresholds.get(session_type, default_threshold)
        active = {
            (row["server"], row["tool"])
            for row in scored_rows
            if row["status"] == "active" and row["score"] >= threshold
        }
        # If threshold filtering leaves nothing, fall back to all active tools
        if not active:
            active = self._active.copy()
        logger.debug(
            f"SessionPool [{session_type}] threshold={threshold}: {len(active)} active tools"
        )
        return SessionPool(active)

    def all_active(self) -> list[tuple[str, str]]:
        """Return all (server, tool) pairs currently in the global active pool."""
        return list(self._active)

    @property
    def is_cold_start(self) -> bool:
        """True when the pool has not yet been seeded from scored data."""
        return self._cold_start


pool = ToolPool()
