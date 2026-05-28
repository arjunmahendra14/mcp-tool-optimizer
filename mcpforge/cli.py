import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import click
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from . import store
from .api import api, init_api
from .config import load_config
from .optimizer import run_optimization, start_scheduler, stop_scheduler
from .pool import pool
from .proxy import build_mcp_server, build_sse_routes, fetch_upstream_tools, init_proxy

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
        for srv in config.servers:
            try:
                tools = await asyncio.wait_for(
                    fetch_upstream_tools(srv), timeout=5.0
                )
                logger.info(f"  ✓ {srv.name}: {len(tools)} tools reachable")
            except asyncio.TimeoutError:
                logger.warning(f"  ✗ {srv.name}: timeout")
            except Exception as e:
                logger.warning(f"  ✗ {srv.name}: {e}")

        pool_size = len(pool.all_active())
        if pool.is_cold_start:
            logger.info("Active pool: cold start — all discovered tools are active")
        else:
            logger.info(f"Active pool: {pool_size} tools")

        start_scheduler(config)
        yield
        stop_scheduler()

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
    """Start proxy + API + optimizer."""
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
    """Print current scores table to stdout."""
    config = load_config(config_path)
    store.init_db(config.database.path)
    rows = store.get_tool_pool()
    if not rows:
        click.echo("No scores yet — run some tool calls first.")
        return
    click.echo(f"{'SERVER':<25} {'TOOL':<35} {'SCORE':>8}  STATUS")
    click.echo("-" * 76)
    for r in rows:
        click.echo(f"{r['server']:<25} {r['tool']:<35} {r['score']:>8.3f}  {r['status']}")


@main.command()
@click.option("--config", "config_path", default="mcpforge.yaml", show_default=True)
def optimize(config_path: str):
    """Trigger one optimization run and print results."""
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
    """Show active pool size and DB stats."""
    config = load_config(config_path)
    store.init_db(config.database.path)
    pool.load_from_db()

    rows = store.get_tool_pool()
    active = sum(1 for r in rows if r["status"] == "active")
    pruned = sum(1 for r in rows if r["status"] == "pruned")
    calls_24h = store.get_tool_calls(hours=24)
    audit = store.get_audit_log(limit=1)

    click.echo(f"DB path:          {config.database.path}")
    click.echo(f"Active tools:     {active}")
    click.echo(f"Pruned tools:     {pruned}")
    click.echo(f"Cold start:       {pool.is_cold_start}")
    click.echo(f"Tool calls (24h): {len(calls_24h)}")
    click.echo(f"Last optimizer:   {audit[0]['ts'] if audit else 'never'}")
