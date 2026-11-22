"""Endpoints for collectors on other computers (token-authenticated) and the
local-only device pairing endpoints used by the dashboard."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from lifeos.config import config
from lifeos.db import get_db
from lifeos.models import Device
from lifeos.serialize import row
from lifeos.services.activity import IngestRejected
from lifeos.services import remote

router = APIRouter(prefix="/api", tags=["collect"])
REPO_ROOT = Path(__file__).resolve().parents[3]


def _device(db: Session, authorization: str | None) -> Device:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    dev = remote.device_for_token(db, token)
    if dev is None:
        raise HTTPException(401, "Unknown or revoked device token. Create a new one under Sources → Devices on the hub.")
    return dev


# ---- collector-facing (reachable from the LAN, token required) --------------------


@router.get("/collect/config")
def collect_config(request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    dev = _device(db, authorization)
    remote.touch_device(db, dev, {
        "version": request.headers.get("x-lifeos-collector"), "platform": request.headers.get("x-lifeos-platform"),
        "aw_version": request.headers.get("x-lifeos-aw"), "hostname": request.headers.get("x-lifeos-hostname"),
    })
    return remote.collector_config(db, dev)


@router.post("/collect/batch")
def collect_batch(batch: dict[str, Any], authorization: str | None = Header(None), db: Session = Depends(get_db)):
    dev = _device(db, authorization)
    try:
        return remote.ingest_batch(db, dev, batch, via="network")
    except IngestRejected as exc:
        raise HTTPException(423 if "paused" in str(exc).lower() else 403, str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, f"Invalid batch: {exc}") from exc


# ---- local-only (dashboard) -------------------------------------------------------


@router.get("/collect/hub-info")
def collect_hub_info():
    return remote.hub_info()


@router.post("/devices/{device_id}/token")
def create_token(device_id: str, db: Session = Depends(get_db)):
    dev = db.get(Device, device_id)
    if not dev:
        raise HTTPException(404)
    token = remote.issue_token(db, dev)
    return {"device_id": dev.id, "token": token, "hub": remote.hub_info(), "note": "Shown once. Creating a new token revokes the old one."}


@router.delete("/devices/{device_id}/token")
def revoke_token(device_id: str, db: Session = Depends(get_db)):
    dev = db.get(Device, device_id)
    if not dev:
        raise HTTPException(404)
    dev.token_hash = None
    db.commit()
    return {"revoked": device_id}


@router.get("/devices/{device_id}/collector-config")
def download_config(device_id: str, db: Session = Depends(get_db)):
    """For file-only mode: rules + settings the collector needs offline (no token inside)."""
    dev = db.get(Device, device_id)
    if not dev:
        raise HTTPException(404)
    body = json.dumps(remote.collector_config(db, dev), default=str, indent=1).encode()
    return StreamingResponse(io.BytesIO(body), media_type="application/json",
                             headers={"Content-Disposition": f'attachment; filename="lifeos-collector-config-{dev.id}.json"'})


@router.get("/collect/package")
def collector_package():
    """Zip of just what a collector needs: the backend package + install scripts."""
    buf = io.BytesIO()
    backend = REPO_ROOT / "backend"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in [backend / "pyproject.toml", backend / "uv.lock", *sorted((backend / "lifeos").rglob("*.py"))]:
            if p.exists() and "__pycache__" not in p.parts:
                zf.write(p, f"lifeos-collector/backend/{p.relative_to(backend)}")
        for name in ["install-collector-windows.ps1", "install-collector-mac.sh"]:
            sp = REPO_ROOT / "scripts" / name
            if sp.exists():
                zf.write(sp, f"lifeos-collector/{name}")
        zf.writestr("lifeos-collector/README.txt", (REPO_ROOT / "docs" / "COLLECTOR.md").read_text() if (REPO_ROOT / "docs" / "COLLECTOR.md").exists() else "See docs/COLLECTOR.md in the LifeOS repo.")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="lifeos-collector.zip"'})


@router.post("/imports/devices/scan")
def import_device_files(db: Session = Depends(get_db)):
    """File-drop fallback: apply batch files from ~/LifeOS/imports/devices/."""
    folder = config.imports_dir / "devices"
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for f in sorted(folder.glob("*.json")):
        try:
            batch = json.loads(f.read_text(encoding="utf-8"))
            dev = db.get(Device, str(batch.get("device_id")))
            if dev is None:
                raise IngestRejected(f"Unknown device {batch.get('device_id')!r}")
            r = remote.ingest_batch(db, dev, batch, via="file")
            done = folder / "imported"
            done.mkdir(exist_ok=True)
            f.replace(done / f.name)
            results.append({"file": f.name, "status": "ok", **r})
        except (IngestRejected, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            results.append({"file": f.name, "status": "error", "error": str(exc)[:200]})
    return {"folder": str(folder), "results": results}


@router.get("/devices/{device_id}/status")
def device_status(device_id: str, db: Session = Depends(get_db)):
    dev = db.get(Device, device_id)
    if not dev:
        raise HTTPException(404)
    return {**row(dev), "has_token": bool(dev.token_hash)}
