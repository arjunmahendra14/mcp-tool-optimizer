import asyncio
import contextvars
import json
import logging
import os
import time
import uuid

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from . import embeddings, store
from .pool import SessionPool, pool

logger = logging.getLogger(__name__)

_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "session_id", default="unknown"
)

# Per-session state
_session_classified: set[str] = set()
_session_types: dict[str, str] = {}
_session_pools: dict[str, SessionPool] = {}
# Per-session tool registry: session_id -> {tool_name -> server_name}.
# Scoped to what each session's tools/list actually returned, so same-named
# tools on different servers route correctly based on what the agent saw.
_session_registries: dict[str, dict[str, str]] = {}

_config = None


def init_proxy(config) -> None:
    global _config
    _config = config


_pool_wait_timeout: float = 30.0
_queue_wait_timeout: float = 5.0
_health_check_task: asyncio.Task | None = None


async def init_upstream_pool(
    servers,
    pool_size: int = 4,
    queue_wait_timeout: float = 5.0,
    pool_wait_timeout: float = 30.0,
    health_check_interval: float = 60.0,
) -> None:
    global _upstream_pool, _pool_wait_timeout, _queue_wait_timeout, _health_check_task
    _pool_wait_timeout = pool_wait_timeout
    _queue_wait_timeout = queue_wait_timeout
    _upstream_pool = _UpstreamPool(size=pool_size)
    for srv in servers:
        try:
            await _upstream_pool.init_server(srv)
        except Exception as e:
            logger.warning(f"Upstream pool: failed to init {srv.name} — {e}")
    _health_check_task = _upstream_pool.start_health_checks(health_check_interval)
    logger.info(f"Upstream pool: health checks every {health_check_interval:.0f}s")


async def close_upstream_pool() -> None:
    global _upstream_pool, _health_check_task
    if _health_check_task:
        _health_check_task.cancel()
        _health_check_task = None
    if _upstream_pool:
        await _upstream_pool.close_all()
        _upstream_pool = None


async def _classify_and_build_session_pool(session_id: str, context: str) -> None:
    from .classifier import classify_session

    session_type = await classify_session(context)
    _session_types[session_id] = session_type
    store.update_session_type(session_id, session_type)

    scored = store.get_tool_pool()
    session_pool = pool.compute_session_pool(
        session_type,
        scored,
        _config.optimizer.thresholds,
        _config.optimizer.default_threshold,
    )

    # Semantic boost: promote reserve tools relevant to this session's task
    semantic_boost = _semantic_boost_for_session(context, scored)
    if semantic_boost:
        from .pool import SessionPool as SP
        session_pool = SP(
            session_pool._active,
            semantic_boost=semantic_boost,
            cold_start=session_pool._cold_start,
        )
        boosted_names = [f"{s}/{t}" for s, t in session_pool.boosted]
        logger.info(f"Session {session_id[:8]} semantic boost: {boosted_names}")

    _session_pools[session_id] = session_pool
    logger.info(
        f"Session {session_id[:8]} classified as '{session_type}' → {session_pool.size} active tools"
    )


def _semantic_boost_for_session(
    context: str,
    pool_rows: list[dict],
    top_k: int = 5,
    threshold: float = 0.4,
) -> set[tuple[str, str]]:
    """Return reserve tools that are semantically relevant to this session's context.

    Only promotes from reserve — excluded tools are never surfaced.
    Returns empty set if no embeddings exist yet.
    """
    tool_embeddings = store.get_tool_embeddings()
    if not tool_embeddings:
        return set()

    reserve = {
        (r["server"], r["tool"])
        for r in pool_rows
        if r["status"] == "reserve"
    }
    if not reserve:
        return set()

    # Only retrieve from the reserve set
    reserve_embeddings = {k: v for k, v in tool_embeddings.items() if k in reserve}
    if not reserve_embeddings:
        return set()

    ranked = embeddings.rank_tools(context, reserve_embeddings, top_k=top_k)
    return {(srv, tool) for srv, tool, score in ranked if score >= threshold}


def _transport(srv):
    """Return the right async context manager for the given ServerConfig."""
    if srv.is_stdio:
        env = {**os.environ, **srv.env} if srv.env else None
        params = StdioServerParameters(command=srv.command, args=srv.args or [], env=env)
        return stdio_client(params)
    return sse_client(srv.url, headers=srv.headers or {})


async def fetch_upstream_tools(srv, timeout: float = 5.0) -> list[types.Tool]:
    """Fetch tools from one upstream server, returning empty list on any failure or timeout."""
    server_name = srv.name
    try:
        async with asyncio.timeout(timeout):
            async with _transport(srv) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    logger.debug(f"  {server_name}: {len(result.tools)} tools")
                    return result.tools
    except TimeoutError:
        logger.warning(f"  {server_name}: timed out after {timeout}s — excluded from pool")
        return []
    except Exception as e:
        logger.warning(f"  {server_name}: unreachable — {e}")
        return []


class _PooledConnection:
    """One live connection to an upstream server, kept open across calls."""

    __slots__ = ("_session", "_exit_stack")

    def __init__(self):
        self._session: ClientSession | None = None
        self._exit_stack = None

    async def connect(self, srv) -> None:
        from contextlib import AsyncExitStack
        self._exit_stack = AsyncExitStack()
        read, write = await self._exit_stack.enter_async_context(_transport(srv))
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()

    async def ping(self, timeout: float = 3.0) -> bool:
        """Return True if the underlying subprocess is still alive."""
        try:
            async with asyncio.timeout(timeout):
                await self._session.list_tools()
            return True
        except Exception:
            return False

    async def call_tool(self, name: str, args: dict) -> types.CallToolResult:
        return await self._session.call_tool(name, args)

    async def close(self) -> None:
        if self._exit_stack:
            await self._exit_stack.aclose()


class _UpstreamPool:
    """Per-server pool of persistent MCP connections.

    Each server gets `size` connections kept alive at startup.
    Callers check out a connection, use it, then return it — no subprocess
    spawned per call. Tool schemas are cached at init time so list_tools
    never spawns a subprocess.
    """

    def __init__(self, size: int = 4):
        self._size = size
        self._queues: dict[str, asyncio.Queue] = {}
        self._srv_configs: dict[str, object] = {}
        self._cached_tools: dict[str, list[types.Tool]] = {}

    async def init_server(self, srv) -> None:
        q: asyncio.Queue = asyncio.Queue()
        cached: list[types.Tool] = []
        for i in range(self._size):
            conn = _PooledConnection()
            await conn.connect(srv)
            if i == 0:
                result = await conn._session.list_tools()
                cached = result.tools
            await q.put(conn)
        self._queues[srv.name] = q
        self._srv_configs[srv.name] = srv
        self._cached_tools[srv.name] = cached
        logger.info(f"Upstream pool: {srv.name} — {self._size} connections, {len(cached)} tools cached")

    def get_tools(self, srv_name: str) -> list[types.Tool]:
        return self._cached_tools.get(srv_name, [])

    async def call_tool(
        self, srv_name: str, tool_name: str, arguments: dict
    ) -> types.CallToolResult:
        q = self._queues[srv_name]
        try:
            conn = await asyncio.wait_for(q.get(), timeout=_queue_wait_timeout)
        except asyncio.TimeoutError:
            raise  # caller catches this and sets is_pool_timeout=True
        return_conn: _PooledConnection | None = conn
        try:
            return await conn.call_tool(tool_name, arguments)
        except BaseException as exc:
            # Close and discard the connection on any error (including CancelledError).
            # A cancelled or errored call may leave the MCP stream in a broken state —
            # re-queuing it would corrupt the next caller's response.
            return_conn = None
            try:
                await conn.close()
            except Exception:
                pass
            # Only replace the connection for real errors, not cancellations.
            # On cancel the pool shrinks temporarily and health-checks refill it.
            if not isinstance(exc, asyncio.CancelledError):
                replacement = _PooledConnection()
                try:
                    await replacement.connect(self._srv_configs[srv_name])
                    return_conn = replacement
                    logger.info(f"Pool: replaced dead connection for {srv_name}")
                except Exception as e:
                    logger.warning(f"Pool: could not replace dead {srv_name} connection — {e}")
            raise
        finally:
            if return_conn is not None:
                await q.put(return_conn)

    async def _health_check_server(self, srv_name: str) -> None:
        """Drain idle connections for one server, ping each, replace any that are dead."""
        q = self._queues[srv_name]
        srv = self._srv_configs[srv_name]

        idle: list[_PooledConnection] = []
        while not q.empty():
            try:
                idle.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not idle:
            return

        replaced = 0
        live: list[_PooledConnection] = []
        for conn in idle:
            if await conn.ping():
                live.append(conn)
            else:
                try:
                    await conn.close()
                except Exception:
                    pass
                replacement = _PooledConnection()
                try:
                    await replacement.connect(srv)
                    live.append(replacement)
                    replaced += 1
                except Exception as e:
                    logger.warning(f"Health check: could not replace dead {srv_name} connection — {e}")

        for conn in live:
            await q.put(conn)

        if replaced:
            logger.info(f"Health check: replaced {replaced}/{len(idle)} dead connections for {srv_name}")

    async def _run_health_checks(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            for srv_name in list(self._queues.keys()):
                try:
                    await self._health_check_server(srv_name)
                except Exception as e:
                    logger.warning(f"Health check error for {srv_name}: {e}")

    def start_health_checks(self, interval: float = 60.0) -> asyncio.Task:
        return asyncio.create_task(self._run_health_checks(interval))

    async def close_all(self) -> None:
        for q in self._queues.values():
            while not q.empty():
                try:
                    conn = q.get_nowait()
                    await conn.close()
                except Exception:
                    pass
        self._queues.clear()


_upstream_pool: _UpstreamPool | None = None


async def call_upstream_tool(srv, tool_name: str, arguments: dict) -> types.CallToolResult:
    if _upstream_pool and srv.name in _upstream_pool._queues:
        return await _upstream_pool.call_tool(srv.name, tool_name, arguments)
    # Fallback: per-call connection (cold-start or pool not yet init'd)
    async with _transport(srv) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


async def _embed_new_tools(servers, tool_results_per_server) -> None:
    """Embed tool descriptions not yet in the store. Fires as a background task."""
    existing = store.get_embedded_tool_texts()
    to_embed = []
    for srv, tools in zip(servers, tool_results_per_server):
        for tool in tools:
            desc_text = embeddings.tool_description_text(
                srv.name, tool.name, tool.description or "", tool.inputSchema or {}
            )
            if existing.get((srv.name, tool.name)) != desc_text:
                to_embed.append((srv.name, tool.name, desc_text))

    if not to_embed:
        return

    try:
        vecs = embeddings.embed([t[2] for t in to_embed])
        for (server_name, tool_name, desc_text), vec in zip(to_embed, vecs):
            store.upsert_tool_embedding(server_name, tool_name, desc_text, vec)
        logger.info(f"Embedded {len(to_embed)} new tool descriptions")
    except Exception as e:
        logger.warning(f"Background tool embedding failed: {e}")


def _record_session_outcome(session_id: str) -> None:
    """Heuristic outcome label captured at SSE disconnect. Not a ground-truth signal."""
    calls = store.get_session_calls(session_id)
    if not calls:
        store.update_session_outcome(session_id, "abandoned", confidence=0.9)
        return

    error_rate = sum(1 for c in calls if not c.get("success", 1)) / len(calls)
    duration = calls[-1]["ts"] - calls[0]["ts"] if len(calls) > 1 else 0

    if error_rate > 0.5:
        store.update_session_outcome(session_id, "error", confidence=0.7)
    elif len(calls) >= 2 and duration > 10:
        store.update_session_outcome(session_id, "completed", confidence=0.6)
    else:
        store.update_session_outcome(session_id, "unknown", confidence=0.0)


def build_mcp_server() -> Server:
    server = Server("mcpforge-proxy")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        if not _config:
            return []

        if _upstream_pool:
            results = [_upstream_pool.get_tools(srv.name) for srv in _config.servers]
        else:
            tasks = [fetch_upstream_tools(srv) for srv in _config.servers]
            results = await asyncio.gather(*tasks)

        session_id = _session_id.get()
        session_pool = _session_pools.get(session_id)
        registry: dict[str, str] = {}

        visible: list[types.Tool] = []
        for srv, tools in zip(_config.servers, results):
            for tool in tools:
                is_active = (
                    session_pool.is_active(srv.name, tool.name)
                    if session_pool is not None
                    else pool.is_active(srv.name, tool.name)
                )
                if is_active and tool.name not in registry:
                    # First active server in config order wins for duplicate names.
                    registry[tool.name] = srv.name
                    visible.append(tool)

        _session_registries[session_id] = registry
        total = sum(len(r) for r in results)
        pool_src = f"session[{_session_types.get(session_id, 'unclassified')}]" if session_pool else "global"
        logger.info(f"tools/list: {len(visible)}/{total} tools visible (pool={pool_src})")

        # Embed any tools not yet in the embedding store (background, non-blocking)
        asyncio.create_task(_embed_new_tools(_config.servers, results))

        return visible

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> types.CallToolResult:
        if not _config:
            raise ValueError("Proxy not initialized")

        session_id = _session_id.get()
        registry = _session_registries.get(session_id, {})
        server_name = registry.get(name)
        if not server_name:
            # Registry is empty (first call before list_tools) — populate it.
            await list_tools()
            server_name = _session_registries.get(session_id, {}).get(name)

        if not server_name:
            raise ValueError(f"Unknown tool: {name}")

        srv_config = next((s for s in _config.servers if s.name == server_name), None)
        if not srv_config:
            raise ValueError(f"No config found for server: {server_name}")

        if session_id not in _session_classified:
            _session_classified.add(session_id)
            context = f"Tool call: {name}\nArguments: {json.dumps(arguments or {})[:300]}"
            asyncio.create_task(_classify_and_build_session_pool(session_id, context))

        t0 = time.perf_counter()
        success = False
        result_size = 0
        is_pool_timeout = False
        result = None
        try:
            result = await call_upstream_tool(srv_config, name, arguments)
            success = not getattr(result, "isError", False)
            result_size = sum(
                len(getattr(c, "text", ""))
                for c in (result.content or [])
            )
        except asyncio.TimeoutError:
            # TimeoutError propagates from the queue-wait inside _UpstreamPool.call_tool
            # when all pool connections are busy. Not a tool execution failure.
            is_pool_timeout = True
            logger.warning(
                f"Queue wait timeout ({_queue_wait_timeout}s) for {server_name}/{name} "
                f"— not counted against tool score"
            )
            result = types.CallToolResult(
                content=[types.TextContent(type="text", text="No pool connection available — all connections busy. Try again.")],
                isError=True,
            )
        finally:
            latency_ms = (time.perf_counter() - t0) * 1000
            session_type = _session_types.get(session_id, "unknown")
            store.log_tool_call(
                session_id, server_name, name, latency_ms, session_type,
                success=success, result_size=result_size, pool_timeout=is_pool_timeout,
            )

        return result

    return server


def build_sse_routes(mcp_server: Server) -> tuple[SseServerTransport, list]:
    sse_transport = SseServerTransport("/messages/")

    async def _handle_sse(scope: Scope, receive: Receive, send: Send) -> Response:
        session_id = str(uuid.uuid4())
        token = _session_id.set(session_id)
        store.create_session(session_id)
        logger.info(f"New SSE connection: {session_id}")
        try:
            async with sse_transport.connect_sse(scope, receive, send) as streams:
                await mcp_server.run(
                    streams[0],
                    streams[1],
                    mcp_server.create_initialization_options(),
                )
        finally:
            _session_id.reset(token)
            _session_classified.discard(session_id)
            _session_types.pop(session_id, None)
            _session_pools.pop(session_id, None)
            _session_registries.pop(session_id, None)
            _record_session_outcome(session_id)
            logger.info(f"SSE connection closed: {session_id}")
        return Response()

    async def handle_sse(request: Request) -> Response:
        return await _handle_sse(request.scope, request.receive, request._send)

    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]
    return sse_transport, routes
