import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import store
from .pool import pool

logger = logging.getLogger(__name__)

api = FastAPI(title="MCPForge Management API", docs_url="/api/docs")
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

_config = None
_run_optimization = None


def init_api(config, run_optimization_fn) -> None:
    global _config, _run_optimization
    _config = config
    _run_optimization = run_optimization_fn


@api.get("/api/health")
async def health():
    active = len(pool.all_active()) if not pool.is_cold_start else -1
    return {
        "status": "ok",
        "pool_size": active,
        "cold_start": pool.is_cold_start,
        "db_path": _config.database.path if _config else "unknown",
    }


@api.get("/api/scores")
async def scores():
    return store.get_tool_pool()


@api.get("/api/pool")
async def get_pool():
    rows = store.get_tool_pool()
    active = [{"server": r["server"], "tool": r["tool"]} for r in rows if r["status"] == "active"]
    reserve = [{"server": r["server"], "tool": r["tool"]} for r in rows if r["status"] == "reserve"]
    return {"active": active, "reserve": reserve}


@api.get("/api/audit")
async def audit():
    return store.get_audit_log(limit=20)


@api.post("/api/optimize")
async def optimize():
    if not _run_optimization or not _config:
        raise HTTPException(status_code=503, detail="Optimizer not initialized")
    result = await _run_optimization(_config, trigger="manual")
    return {"scores": result}


class RollbackRequest(BaseModel):
    run_id: int


@api.post("/api/rollback")
async def rollback(req: RollbackRequest):
    """Restore pool to the state captured in a given audit entry."""
    entry = store.get_audit_entry(req.run_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Audit entry {req.run_id} not found")

    before = {(r["server"], r["tool"]): r["status"] for r in store.get_tool_pool()}
    snapshot = json.loads(entry["pool_snapshot_json"])
    store.restore_tool_pool(snapshot)
    pool.load_from_db()

    after = {(r["server"], r["tool"]): r["status"] for r in store.get_tool_pool()}
    changes = {
        f"{k[0]}__{k[1]}": {"before": before.get(k, "absent"), "after": after.get(k, "absent")}
        for k in set(before) | set(after)
        if before.get(k) != after.get(k)
    }
    store.write_audit_log("rollback", changes, store.get_tool_pool())

    logger.info(f"Rolled back pool to audit entry {req.run_id} ({len(changes)} changes)")
    return {"rolled_back_to": req.run_id, "pool_size": len(snapshot), "changes": len(changes)}
