"""Activity timeline, corrections, ingestion, categories, rules, devices."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from lifeos import schemas
from lifeos.db import get_db
from lifeos.models import (
    ActivityCategory,
    ActivityEvent,
    Checkin,
    ClassificationRule,
    CollectorStatus,
    Device,
    MusicSignal,
    SessionStateChange,
    ClaudeSession,
    TaskMilestone,
    Task,
)
from lifeos.serialize import row
from lifeos.services import activity as act
from lifeos.services.activitywatch import aw_probe, sync_activitywatch
from lifeos.services.classification import reclassify_events, validate_rule_pattern
from lifeos.services.patterns import episode_out, episodes_for_range
from lifeos.services.imports import ingest_events, parse_activity_file
from lifeos.services.settings import get_settings
from lifeos.timeutil import local_day_bounds, local_today, utcnow

router = APIRouter(prefix="/api", tags=["activity"])


def _event_out(e: ActivityEvent) -> dict[str, Any]:
    return {
        **row(e),
        "effective_category": e.effective_category,
        "effective_confidence": e.effective_confidence,
        "effective_subcategory": e.effective_subcategory,
        "duration_seconds": e.duration_seconds,
    }


@router.get("/today")
def today_view(day: date | None = None, db: Session = Depends(get_db)):
    s = get_settings(db)
    tz_name = s["timezone"]
    day = day or local_today(tz_name)
    lo, hi = local_day_bounds(day, tz_name)
    hi_eff = min(hi, utcnow()) if day == local_today(tz_name) else hi
    events = act.events_in_range(db, lo, hi)
    blocks = act.timeline_blocks(events, lo, hi_eff, timedelta(seconds=s["activitywatch"]["merge_gap_seconds"] * 5))
    summary = act.category_summary(events, lo, hi_eff)

    markers: list[dict[str, Any]] = []
    for c in db.query(Checkin).filter(Checkin.at >= lo, Checkin.at < hi):
        markers.append({"at": c.at, "type": "checkin", "domain": c.domain, "kind": c.kind, "title": c.title or c.kind.replace("_", " ")})
    for m in db.query(MusicSignal).filter(MusicSignal.at >= lo, MusicSignal.at < hi):
        markers.append({"at": m.at, "type": "music_file", "domain": "music", "kind": m.kind, "title": f"{m.project_name}: {m.kind.replace('_', ' ')}"})
    for ms, t in db.query(TaskMilestone, Task).join(Task).filter(TaskMilestone.completed_at >= lo, TaskMilestone.completed_at < hi):
        markers.append({"at": ms.completed_at, "type": "milestone", "domain": t.domain, "kind": "milestone", "title": f"{t.title}: {ms.title}"})
    for ch, sess in db.query(SessionStateChange, ClaudeSession).join(ClaudeSession).filter(SessionStateChange.at >= lo, SessionStateChange.at < hi, SessionStateChange.to_state.in_(["ready", "completed"])):
        markers.append({"at": ch.at, "type": "session", "domain": "software", "kind": ch.to_state, "title": f"{sess.project or 'Claude'} → {ch.to_state}"})
    markers.sort(key=lambda m: m["at"])

    episodes, detours = episodes_for_range(db, lo, hi_eff)
    excluded = db.query(ActivityEvent).filter(ActivityEvent.start_time < hi, ActivityEvent.end_time > lo, ActivityEvent.excluded.is_(True)).count()
    aw = db.get(CollectorStatus, "activitywatch")
    return {
        "day": day,
        "timezone": tz_name,
        "range": {"start": lo, "end": hi, "now": utcnow()},
        "blocks": [b.__dict__ for b in blocks],
        "summary": summary,
        "markers": markers,
        "episodes": [episode_out(e) for e in episodes],
        "devices": [{"id": d.id, "name": d.name, "is_work": d.is_work, "content_free": d.content_free}
                    for d in db.query(Device).filter(Device.id.in_({b.device_id for b in blocks if b.device_id}))],
        "detours": detours,
        "excluded_count": excluded,
        "collection": {
            "paused": s["privacy"]["collection_paused"],
            "activitywatch": row(aw) if aw else None,
        },
    }


@router.get("/activity/events")
def list_events(
    start: date, end: date | None = None, q: str | None = None, category: str | None = None,
    ids: list[int] = Query(default=[]), db: Session = Depends(get_db),
):
    if ids:
        return [_event_out(e) for e in sorted(act.find_events_by_ids(db, ids), key=lambda e: e.start_time)]
    tz_name = get_settings(db)["timezone"]
    lo, _ = local_day_bounds(start, tz_name)
    _, hi = local_day_bounds(end or start, tz_name)
    return [_event_out(e) for e in act.search_events(db, lo, hi, q, category)]


@router.patch("/activity/events")
def patch_events(body: schemas.EventPatch, db: Session = Depends(get_db)):
    if body.category and db.get(ActivityCategory, body.category) is None:
        raise HTTPException(400, "Unknown category")
    rows = act.find_events_by_ids(db, body.ids)
    for e in rows:
        if body.category:
            e.category_override = body.category
        if body.clear_override:
            e.category_override = None
        if body.excluded is not None:
            e.excluded = body.excluded
        if body.confirmed is not None:
            e.confirmed = body.confirmed
    db.commit()
    return {"updated": len(rows)}


@router.post("/activity/ingest")
def ingest(body: schemas.IngestBody, db: Session = Depends(get_db)):
    run = ingest_events(db, body.device_id, body.events)
    if run.status == "error":
        raise HTTPException(400, run.error)
    return row(run)


@router.post("/activity/import-file")
async def import_file(device_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    try:
        events = parse_activity_file(file.filename or "upload.csv", content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not parse file ({type(exc).__name__})") from exc
    run = ingest_events(db, device_id, events, file.filename)
    return row(run)


@router.post("/activitywatch/sync")
def aw_sync(days_back: int = 0, db: Session = Depends(get_db)):
    days = None
    if days_back > 0:
        today = local_today(get_settings(db)["timezone"])
        days = [today - timedelta(days=i) for i in range(days_back, -1, -1)]
    return sync_activitywatch(db, days=days)


@router.get("/activitywatch/probe")
def aw_status(db: Session = Depends(get_db)):
    s = get_settings(db)["activitywatch"]
    status = db.get(CollectorStatus, "activitywatch")
    return {"config": s, "probe": aw_probe(s["url"]), "status": row(status) if status else None}


# ---- categories --------------------------------------------------------------
@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    return [row(c) for c in db.query(ActivityCategory).order_by(ActivityCategory.sort_order)]


@router.post("/categories")
def create_category(body: schemas.CategoryIn, db: Session = Depends(get_db)):
    if db.get(ActivityCategory, body.key):
        raise HTTPException(409, "Category already exists")
    n = db.query(ActivityCategory).count()
    c = ActivityCategory(**body.model_dump(), sort_order=n)
    db.add(c)
    db.commit()
    return row(c)


@router.patch("/categories/{key}")
def patch_category(key: str, body: schemas.CategoryPatch, db: Session = Depends(get_db)):
    c = db.get(ActivityCategory, key)
    if not c:
        raise HTTPException(404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    return row(c)


# ---- rules -------------------------------------------------------------------
@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    return [row(r) for r in db.query(ClassificationRule).order_by(ClassificationRule.priority, ClassificationRule.id)]


def _check_rule(db: Session, match_type: str, pattern: str, category: str) -> None:
    try:
        validate_rule_pattern(match_type, pattern)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if db.get(ActivityCategory, category) is None:
        raise HTTPException(400, "Unknown category")


@router.post("/rules")
def create_rule(body: schemas.RuleIn, reclassify: bool = True, db: Session = Depends(get_db)):
    _check_rule(db, body.match_type, body.pattern, body.category_key)
    r = ClassificationRule(**body.model_dump())
    db.add(r)
    db.commit()
    changed = reclassify_events(db) if reclassify else 0
    return {**row(r), "reclassified": changed}


@router.post("/rules/from-event")
def rule_from_event(body: schemas.RuleFromEvent, db: Session = Depends(get_db)):
    e = db.get(ActivityEvent, body.event_id)
    if not e:
        raise HTTPException(404)
    value = getattr(e, body.field)
    if not value:
        raise HTTPException(400, f"Event has no {body.field}")
    _check_rule(db, "equals", value, body.category_key)
    r = ClassificationRule(name=f"{body.field}: {value}", field=body.field, match_type="equals", pattern=value,
                           category_key=body.category_key, confidence="medium", priority=1)
    db.add(r)
    db.commit()
    return {**row(r), "reclassified": reclassify_events(db)}


@router.patch("/rules/{rule_id}")
def patch_rule(rule_id: int, body: schemas.RulePatch, db: Session = Depends(get_db)):
    r = db.get(ClassificationRule, rule_id)
    if not r:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    _check_rule(db, data.get("match_type", r.match_type), data.get("pattern", r.pattern), data.get("category_key", r.category_key))
    for k, v in data.items():
        setattr(r, k, v)
    db.commit()
    return {**row(r), "reclassified": reclassify_events(db)}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    r = db.get(ClassificationRule, rule_id)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"deleted": rule_id, "reclassified": reclassify_events(db)}


@router.post("/rules/reclassify")
def reclassify(db: Session = Depends(get_db)):
    return {"reclassified": reclassify_events(db)}


# ---- devices -----------------------------------------------------------------
@router.get("/devices")
def list_devices(db: Session = Depends(get_db)):
    out = []
    for d in db.query(Device).order_by(Device.created_at):
        last = db.query(ActivityEvent.end_time).filter(ActivityEvent.device_id == d.id).order_by(ActivityEvent.end_time.desc()).first()
        out.append({**row(d), "last_event_at": last[0] if last else None, "has_token": bool(d.token_hash), "content_free": d.content_free})
    return out


@router.post("/devices")
def create_device(body: schemas.DeviceIn, db: Session = Depends(get_db)):
    if db.get(Device, body.id):
        raise HTTPException(409, "Device already exists")
    data = body.model_dump()
    if data["is_work"]:
        # Safe defaults for work machines: never titles, aggregate unless approved.
        data["store_titles"] = False
        data["aggregate_only"] = True if not data["monitoring_approved"] else data["aggregate_only"]
    d = Device(**data)
    db.add(d)
    db.commit()
    return row(d)


@router.patch("/devices/{device_id}")
def patch_device(device_id: str, body: schemas.DevicePatch, db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    if d.is_work:
        d.store_titles = False
    db.commit()
    return row(d)


@router.delete("/devices/{device_id}")
def delete_device(device_id: str, purge: bool = False, db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if not d:
        raise HTTPException(404)
    n = db.query(ActivityEvent).filter(ActivityEvent.device_id == device_id).count()
    if n and not purge:
        raise HTTPException(409, f"Device has {n} events. Pass purge=true to delete them too.")
    db.query(ActivityEvent).filter(ActivityEvent.device_id == device_id).delete()
    db.delete(d)
    db.commit()
    return {"deleted": device_id, "events_deleted": n}
