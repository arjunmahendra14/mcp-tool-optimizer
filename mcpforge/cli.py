import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import click
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from . import embeddings, store
from .api import api, init_api
from .config import load_config
from .optimizer import run_optimization, start_scheduler, stop_scheduler
from .pool import pool
from .proxy import (
    build_mcp_server, build_sse_routes, fetch_upstream_tools,
    init_proxy, init_upstream_pool, close_upstream_pool,
)

def _load_dotenv(path: str = ".env") -> None:
    """Load key=value pairs from a .env file into os.environ, skipping keys already set."""
    env_file = Path(path)
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def _embed_tools(all_tools: list[tuple]) -> None:
    """Generate and store embeddings for tool descriptions. Skips unchanged tools."""
    if not all_tools:
        return

    existing_texts = store.get_embedded_tool_texts()
    to_embed = []

    for server_name, tool in all_tools:
        desc_text = embeddings.tool_description_text(
            server_name,
            tool.name,
            tool.description or "",
            tool.inputSchema or {},
        )
        if existing_texts.get((server_name, tool.name)) != desc_text:
            to_embed.append((server_name, tool.name, desc_text))

    if not to_embed:
        logger.info("Tool embeddings: all up to date")
        return

    logger.info(f"Embedding {len(to_embed)} tool descriptions...")
    texts = [t[2] for t in to_embed]
    try:
        vecs = embeddings.embed(texts)
        for (server_name, tool_name, desc_text), vec in zip(to_embed, vecs):
            store.upsert_tool_embedding(server_name, tool_name, desc_text, vec)
        logger.info(f"Tool embeddings: stored {len(to_embed)} vectors")
    except Exception as e:
        logger.warning(f"Tool embedding failed: {e}")


def _tool_schema_tokens(tool) -> int:
    """Estimate token cost of a tool's full schema definition."""
    obj = {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema or {},
    }
    return max(1, len(json.dumps(obj)) // 4)


def build_app(config):
    store.init_db(config.database.path)
    pool.load_from_db()
    init_proxy(config)
    init_api(config, run_optimization)

    mcp_server = build_mcp_server()
    _sse_transport, sse_routes = build_sse_routes(mcp_server)

    @asynccontextmanager
    async def lifespan(app):
        logger.info("Checking upstream server connectivity...")
        all_tools: list[tuple] = []
        for srv in config.servers:
            try:
                tools = await asyncio.wait_for(
                    fetch_upstream_tools(srv), timeout=5.0
                )
                logger.info(f"  ✓ {srv.name}: {len(tools)} tools reachable")
                all_tools.extend((srv.name, t) for t in tools)
                for t in tools:
                    store.upsert_tool_schema_tokens(srv.name, t.name, _tool_schema_tokens(t))
            except asyncio.TimeoutError:
                logger.warning(f"  ✗ {srv.name}: timeout")
            except Exception as e:
                logger.warning(f"  ✗ {srv.name}: {e}")

        pool_size = len(pool.all_active())
        if pool.is_cold_start:
            logger.info("Active pool: cold start — all discovered tools are active")
        else:
            logger.info(f"Active pool: {pool_size} tools")

        await _embed_tools(all_tools)

        # Pre-warm the embedding backend in a thread so the first tools/list call
        # doesn't block the event loop loading a large model (e.g. sentence-transformers).
        await asyncio.get_event_loop().run_in_executor(None, embeddings._init_backend)

        await init_upstream_pool(
            config.servers,
            pool_size=config.proxy.pool_size,
            queue_wait_timeout=config.proxy.queue_wait_timeout,
            pool_wait_timeout=config.proxy.pool_wait_timeout,
            health_check_interval=config.proxy.health_check_interval,
        )
        start_scheduler(config)
        yield
        stop_scheduler()
        await close_upstream_pool()

    return Starlette(
        routes=[
            *sse_routes,
            Mount("/", app=api),
        ],
        lifespan=lifespan,
    )


@click.group()
def main():
    pass


@main.command()
@click.option("--config", "config_path", default="mcpforge.yaml", show_default=True)
@click.option("--env-file", "env_file", default=".env", show_default=True, help="Path to .env file")
def start(config_path: str, env_file: str):
    """Start the proxy, API, and optimizer. Begins learning from tool calls immediately — no configuration required beyond server URLs."""
    _load_dotenv(env_file)
    config = load_config(config_path)

    logger.info("MCPForge v2 starting")
    logger.info(f"Servers: {[s.name for s in config.servers]}")
    logger.info(f"Proxy:   {config.proxy.host}:{config.proxy.port}")
    logger.info(f"DB:      {config.database.path}")

    app = build_app(config)

    uvicorn.run(
        app,
        host=config.proxy.host,
        port=config.proxy.port,
        log_level="warning",
    )


@main.command()
@click.option("--config", "config_path", default="mcpforge.yaml", show_default=True)
def scores(config_path: str):
    """Print current tool scores with token costs and utility density."""
    config = load_config(config_path)
    store.init_db(config.database.path)
    rows = store.get_tool_pool()
    if not rows:
        click.echo("No scores yet — run some tool calls first.")
        return

    total_tokens = sum(r.get("schema_tokens", 1) for r in rows)
    active_tokens = sum(r.get("schema_tokens", 1) for r in rows if r["status"] == "active")
    budget = config.optimizer.token_budget
    saved = total_tokens - active_tokens

    click.echo(f"Token budget: {active_tokens:,}/{budget:,} used  |  {saved:,} tokens saved vs full pool ({total_tokens:,})")
    click.echo()
    click.echo(f"{'SERVER':<20} {'TOOL':<32} {'SCORE':>7}  {'TOKENS':>6}  {'UTIL/TOK':>9}  STATUS")
    click.echo("-" * 88)
    for r in rows:
        tokens = r.get("schema_tokens", 1)
        util_per_tok = r["score"] / tokens if tokens > 0 else 0.0
        click.echo(
            f"{r['server']:<20} {r['tool']:<32} {r['score']:>7.3f}  {tokens:>6,}  {util_per_tok:>9.5f}  {r['status']}"
        )


@main.command()
@click.option("--config", "config_path", default="mcpforge.yaml", show_default=True)
def optimize(config_path: str):
    """Trigger one optimization run and print the results. Normally runs automatically on a schedule — use this to force an immediate run."""
    config = load_config(config_path)
    store.init_db(config.database.path)
    pool.load_from_db()

    async def _run():
        result = await run_optimization(config, trigger="cli")
        if result:
            click.echo(f"{'SERVER':<25} {'TOOL':<35} {'SCORE':>8}  STATUS")
            click.echo("-" * 76)
            for item in result:
                click.echo(
                    f"{item['server']:<25} {item['tool']:<35} {item['score']:>8.3f}  {item['status']}"
                )
        else:
            click.echo("No usage data — nothing to optimize.")

    asyncio.run(_run())


@main.command()
@click.option("--config", "config_path", default="mcpforge.yaml", show_default=True)
def status(config_path: str):
    """Show active vs. pruned tool count, calls in the last 24h, and when the last optimization ran."""
    config = load_config(config_path)
    store.init_db(config.database.path)
    pool.load_from_db()

    rows = store.get_tool_pool()
    active = sum(1 for r in rows if r["status"] == "active")
    reserve = sum(1 for r in rows if r["status"] == "reserve")
    calls_24h = store.get_tool_calls(hours=24)
    audit = store.get_audit_log(limit=1)

    click.echo(f"DB path:          {config.database.path}")
    click.echo(f"Active tools:     {active}")
    click.echo(f"Reserve tools:    {reserve}")
    click.echo(f"Cold start:       {pool.is_cold_start}")
    click.echo(f"Tool calls (24h): {len(calls_24h)}")
    click.echo(f"Last optimizer:   {audit[0]['ts'] if audit else 'never'}")
