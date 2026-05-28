"""In-memory tool pools — global pool and per-session scoped pools."""

import logging

from . import store

logger = logging.getLogger(__name__)


class SessionPool:
    """Active tool pool scoped to a single MCP session."""

    def __init__(self, active: set[tuple[str, str]], cold_start: bool = False) -> None:
        self._active = active
        self._cold_start = cold_start

    def is_active(self, server: str, tool: str) -> bool:
        """Return True if this (server, tool) pair is active in this session's pool."""
        if self._cold_start:
            return True
        return (server, tool) in self._active

    @property
    def size(self) -> int:
        """Number of active tools in this session pool."""
        return len(self._active)


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
        """Replace the global pool with optimizer results."""
        self._active = {
            (t["server"], t["tool"])
            for t in scored_tools
            if t["status"] == "active"
        }
        self._cold_start = False
        logger.info(f"Pool updated: {len(self._active)} active tools")

    def compute_session_pool(
        self,
        session_type: str,
        scored_rows: list[dict],
        thresholds: dict[str, float],
        default_threshold: float,
    ) -> SessionPool:
        """Build a session-scoped pool applying the type-specific prune threshold.

        In cold-start mode, all tools are active regardless of threshold.
        """
        if self._cold_start:
            return SessionPool(set(), cold_start=True)

        threshold = thresholds.get(session_type, default_threshold)
        active = {
            (row["server"], row["tool"])
            for row in scored_rows
            if row["score"] >= threshold
        }
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
