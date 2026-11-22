"""LifeOS FastAPI application.

Run:  uv run lifeos            (or: uv run uvicorn lifeos.main:app --port 8765)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lifeos.config import config
from lifeos.db import SessionLocal, create_all, init_engine
from lifeos.migrate import migrate
import ipaddress

from fastapi import Request
from fastapi.responses import JSONResponse

from lifeos.routers import activity, collect, life, work
from lifeos.seed import seed_defaults
from lifeos.serialize import UTCJSONResponse
from lifeos.services.activitywatch import sync_activitywatch
from lifeos.services.imports import scan_music
from lifeos.services.settings import get_settings

log = logging.getLogger("lifeos")


def init_app_db(db_path=None) -> None:
    if db_path is None:
        config.ensure_dirs()
        db_path = config.db_path
    engine = init_engine(db_path)
    create_all()
    applied = migrate(engine)
    if applied:
        log.info("Applied migrations: %s", ", ".join(applied))
    with SessionLocal() as db:
        seed_defaults(db)


async def _background_sync() -> None:
    """Periodic ActivityWatch sync + music folder scan. Failures are recorded, never fatal."""
    await asyncio.sleep(3)
    tick = 0
    while True:
        interval = 5
        try:
            with SessionLocal() as db:
                s = get_settings(db)
                interval = max(1, int(s["activitywatch"]["interval_minutes"]))
                if not s["privacy"]["collection_paused"]:
                    await asyncio.to_thread(sync_activitywatch, db)
            with SessionLocal() as db:
                if (config.imports_dir / "devices").exists() and any((config.imports_dir / "devices").glob("*.json")):
                    from lifeos.routers.collect import import_device_files

                    await asyncio.to_thread(import_device_files, db)
            if tick % 6 == 0:
                with SessionLocal() as db:
                    if not get_settings(db)["privacy"]["collection_paused"]:
                        await asyncio.to_thread(scan_music, db, 2)
        except Exception:  # noqa: BLE001
            log.exception("background sync failed")
        tick += 1
        await asyncio.sleep(interval * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not getattr(app.state, "skip_init", False):
        init_app_db()
    task = asyncio.create_task(_background_sync()) if config.background_sync and not getattr(app.state, "skip_init", False) else None
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="LifeOS", version="0.1.0", lifespan=lifespan, default_response_class=UTCJSONResponse)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# ---- network guard ------------------------------------------------------------
# The hub may listen on the home network so other computers can send data. Only
# the token-protected collector endpoints are reachable that way; the dashboard
# API and everything else answer to this Mac only.
# /api/collect/package is program code only (no data, no tokens), so a new
# computer can download the collector straight from the hub.
REMOTE_ALLOWED = {"/api/collect/config", "/api/collect/batch", "/api/collect/package", "/api/health"}


def is_local_client(host: str | None) -> bool:
    if host in {"127.0.0.1", "::1", "localhost"}:
        return True
    return host == "testclient" and getattr(app.state, "skip_init", False)


def is_private_network(host: str | None) -> bool:
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")  # incl. Tailscale CGNAT


@app.middleware("http")
async def network_guard(request: Request, call_next):
    host = request.client.host if request.client else None
    if not is_local_client(host):
        if request.url.path not in REMOTE_ALLOWED or not is_private_network(host):
            return JSONResponse({"detail": "Not available from other computers."}, status_code=403)
    return await call_next(request)


app.include_router(collect.router)
app.include_router(activity.router)
app.include_router(work.router)
app.include_router(life.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def run() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run("lifeos.main:app", host=config.host, port=config.port, reload=False)
