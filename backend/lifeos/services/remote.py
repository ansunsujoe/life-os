"""Multi-device collection: device tokens, collector config, batch ingestion.

Collectors on other computers read their own local ActivityWatch and send one
batch per (day, window bucket). A batch fully describes that day for that
bucket, so re-sending is idempotent and stale pieces are removed. The same
batch format is used for file-drop imports when the network isn't available.

Work devices (`Device.content_free`) classify locally and send only categories
and times; the hub additionally strips anything else (see activity._apply).
"""

from __future__ import annotations

import hashlib
import secrets
import socket
import subprocess
import sys
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from lifeos.config import config
from lifeos.models import ClassificationRule, Device, ImportRun
from lifeos.services.activity import IngestRejected, NormalizedEvent, check_device_allowed
from lifeos.services.activitywatch import _replace_day
from lifeos.services.classification import load_classifier
from lifeos.services.patterns import apply_patterns
from lifeos.services.settings import get_settings
from lifeos.timeutil import local_day_bounds, parse_iso, utcnow

BATCH_FORMAT = "lifeos-batch/1"
MAX_EVENTS_PER_BATCH = 20000


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, device: Device) -> str:
    token = "lfs_" + secrets.token_urlsafe(32)
    device.token_hash = hash_token(token)
    db.commit()
    return token


def device_for_token(db: Session, token: str | None) -> Device | None:
    if not token:
        return None
    return db.query(Device).filter(Device.token_hash == hash_token(token.strip())).one_or_none()


def collector_config(db: Session, device: Device) -> dict[str, Any]:
    """Everything a collector needs to classify locally (rules contain no personal data)."""
    s = get_settings(db)
    rules = db.query(ClassificationRule).filter(ClassificationRule.enabled.is_(True)).order_by(ClassificationRule.priority).all()
    return {
        "format": "lifeos-collector-config/1",
        "device": {
            "id": device.id, "name": device.name, "is_work": device.is_work, "content_free": device.content_free,
            "collection_enabled": device.collection_enabled, "monitoring_approved": device.monitoring_approved,
        },
        "paused": s["privacy"]["collection_paused"],
        "timezone": s["timezone"],
        "first_sync_lookback_hours": s["activitywatch"]["first_sync_lookback_hours"],
        "store_full_urls": s["privacy"]["store_full_urls"] and not device.content_free,
        "attention": s["attention"],
        "rules": [
            {"id": r.id, "field": r.field, "match_type": r.match_type, "pattern": r.pattern, "category": r.category_key,
             "confidence": r.confidence, "label": r.activity_label, "subcategory": r.subcategory, "priority": r.priority}
            for r in rules
        ],
        "server_time": utcnow(),
    }


def namespaced_bucket(device: Device, bucket: str) -> str:
    """Remote keys always carry the device id, so a remote batch can never touch
    another device's events, even if two computers report the same bucket name."""
    return f"dev={device.id}/{bucket}"


def _event_from_payload(device: Device, bucket: str, day: date, raw: dict[str, Any]) -> NormalizedEvent:
    ev_id, piece = raw["aw_event_id"], int(raw.get("piece", 0))
    start, end = parse_iso(str(raw["start_time"])), parse_iso(str(raw["end_time"]))
    key = f"aw:{namespaced_bucket(device, bucket)}:{day.isoformat()}:{ev_id}:{piece}"
    if device.content_free:
        return NormalizedEvent(
            source_key=key, source="activitywatch", device_id=device.id, start_time=start, end_time=end,
            category=raw.get("category") or "other", subcategory=raw.get("subcategory"), confidence=raw.get("confidence") or "low",
            evidence={k: v for k, v in (raw.get("evidence") or {}).items() if k in {"afk_filtered", "pattern"}},
        )
    return NormalizedEvent(
        source_key=key, source="activitywatch", device_id=device.id, start_time=start, end_time=end,
        app=raw.get("app"), title=raw.get("title"), domain=raw.get("domain"), evidence=raw.get("evidence") or {},
    )


def ingest_batch(db: Session, device: Device, batch: dict[str, Any], via: str = "network") -> dict[str, Any]:
    """Validate and apply one day-batch from a collector. Raises IngestRejected/ValueError."""
    if batch.get("format", BATCH_FORMAT) != BATCH_FORMAT:
        raise ValueError(f"Unsupported batch format {batch.get('format')!r}")
    if batch.get("device_id") not in (None, device.id):
        raise IngestRejected("Batch belongs to a different device.")
    s = get_settings(db)
    if s["privacy"]["collection_paused"]:
        raise IngestRejected("Collection is paused on the hub.")
    check_device_allowed(device, aggregate=device.content_free)
    day = date.fromisoformat(str(batch["day"]))
    bucket = str(batch["bucket_id"])[:128]
    if not bucket.startswith("aw-watcher-window"):
        raise ValueError("Unexpected bucket id")
    events = batch.get("events") or []
    if len(events) > MAX_EVENTS_PER_BATCH:
        raise ValueError("Batch too large")
    today = utcnow().date()
    if day > today + timedelta(days=1) or day < today - timedelta(days=400):
        raise ValueError("Batch day out of range")

    run = ImportRun(kind="collector", filename=f"{device.id} {day} via {via}", device_id=device.id)
    db.add(run)
    db.commit()
    normalized = [_event_from_payload(device, bucket, day, e) for e in events]
    store_titles = s["privacy"]["store_window_titles"] and device.store_titles and not device.content_free
    added, updated, removed = _replace_day(db, namespaced_bucket(device, bucket), day, normalized, store_titles, run.id, load_classifier(db))
    if not device.content_free:
        lo, hi = local_day_bounds(day, s["timezone"])
        apply_patterns(db, lo, hi)
    run.records_seen, run.records_added, run.records_updated, run.records_skipped = len(events), added, updated, removed
    run.status, run.finished_at = "ok", utcnow()
    device.last_seen_at = utcnow()
    db.commit()
    return {"day": day.isoformat(), "added": added, "updated": updated, "removed": removed}


def touch_device(db: Session, device: Device, info: dict[str, Any]) -> None:
    device.last_seen_at = utcnow()
    clean = {k: str(v)[:80] for k, v in info.items() if k in {"version", "platform", "aw_version", "hostname", "python"} and v}
    if clean:
        device.collector_info = {**(device.collector_info or {}), **clean}
    db.commit()


def _local_hostname() -> str:
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["/usr/sbin/scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=2).stdout.strip()
            if out:
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    return socket.gethostname().split(".")[0]


def _lan_ips() -> list[str]:
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # no packet is sent; picks the outbound interface
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.")]


def hub_info() -> dict[str, Any]:
    listening_on_lan = config.host not in {"127.0.0.1", "localhost", "::1"}
    host = _local_hostname()
    urls = [f"http://{host}.local:{config.port}"] + [f"http://{ip}:{config.port}" for ip in _lan_ips()]
    return {"listening_on_lan": listening_on_lan, "bind": config.host, "port": config.port, "urls": urls, "hostname": host}
