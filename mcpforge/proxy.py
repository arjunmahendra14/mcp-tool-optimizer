import asyncio
import contextvars
import json
import logging
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

from . import store
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
    _session_pools[session_id] = session_pool
    logger.info(
        f"Session {session_id[:8]} classified as '{session_type}' → {session_pool.size} active tools"
    )


def _transport(srv):
    """Return the right async context manager for the given ServerConfig."""
    if srv.is_stdio:
        params = StdioServerParameters(command=srv.command, args=srv.args or [])
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


async def call_upstream_tool(srv, tool_name: str, arguments: dict) -> types.CallToolResult:
    async with _transport(srv) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


def build_mcp_server() -> Server:
    server = Server("mcpforge-proxy")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        if not _config:
            return []

        tasks = [
            fetch_upstream_tools(srv)
            for srv in _config.servers
        ]
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
        try:
            result = await call_upstream_tool(srv_config, name, arguments)
        finally:
            latency_ms = (time.perf_counter() - t0) * 1000
            session_type = _session_types.get(session_id, "unknown")
            store.log_tool_call(session_id, server_name, name, latency_ms, session_type)

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
            logger.info(f"SSE connection closed: {session_id}")
        return Response()

    async def handle_sse(request: Request) -> Response:
        return await _handle_sse(request.scope, request.receive, request._send)

    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]
    return sse_transport, routes
