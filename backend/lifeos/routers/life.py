"""Check-ins, daily review, trading notes, imports, scores, recommendations,
insights, settings, privacy controls, and data export/deletion."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from lifeos import schemas
from lifeos.config import config
from lifeos.db import Base, get_db
from lifeos.importers.robinhood import TRADE_CODES
from lifeos.models import (
    ActivityEvent,
    Checkin,
    ClaudeSession,
    CollectorStatus,
    DailyReview,
    HealthMetric,
    ImportRun,
    MusicSignal,
    RecommendationFeedback,
    SessionStateChange,
    TradingEvent,
    TradingNote,
)
from lifeos.serialize import jsonify, row
from lifeos.services import imports as imp
from lifeos.services.activity import COMPUTER_SOURCES, category_summary, event_interval, events_in_range
from lifeos.services.goals import milestones_in_range
from lifeos.services.intervals import continuous_stretches, union
from lifeos.services.orchestrator import recommend
from lifeos.services.recovery import current_assessment
from lifeos.services.scoring import compute_orchestration, compute_score
from lifeos.services.settings import DEFAULT_SETTINGS, get_settings, update_settings
from lifeos.timeutil import get_zone, local_day_bounds, local_range_bounds, local_today, to_local, to_utc_naive, utcnow, week_start

router = APIRouter(prefix="/api", tags=["life"])


def _tz(db: Session) -> str:
    return get_settings(db)["timezone"]


# ---- check-ins ---------------------------------------------------------------
@router.get("/checkins")
def list_checkins(start: date | None = None, end: date | None = None, domain: str | None = None, db: Session = Depends(get_db)):
    tz_name = _tz(db)
    end = end or local_today(tz_name)
    start = start or end - timedelta(days=6)
    lo, hi = local_range_bounds(start, end, tz_name)
    q = db.query(Checkin).filter(Checkin.at >= lo, Checkin.at < hi)
    if domain:
        q = q.filter(Checkin.domain == domain)
    return [row(c) for c in q.order_by(Checkin.at.desc())]


@router.post("/checkins")
def create_checkin(body: schemas.CheckinIn, db: Session = Depends(get_db)):
    tz_name = _tz(db)
    data = body.model_dump()
    data["at"] = data["at"] or utcnow()
    data["details"] = {**data["details"], "local_day": to_local(data["at"], tz_name).date().isoformat()}
    c = Checkin(**data, source="manual")
    db.add(c)
    db.commit()
    return row(c)


@router.delete("/checkins/{cid}")
def delete_checkin(cid: int, db: Session = Depends(get_db)):
    c = db.get(Checkin, cid)
    if not c:
        raise HTTPException(404)
    db.delete(c)
    db.commit()
    return {"deleted": cid}


# ---- daily review ------------------------------------------------------------
REVIEW_DERIVED = {
    # field → (domain, kind, title)
    "scripture_prayer": ("faith", "scripture_prayer", "Scripture / prayer"),
    "service_action": ("faith", "service", "Christian action / service"),
    "music_progress": ("music", "progress", "Music progress"),
}


@router.get("/reviews/{day}")
def get_review(day: date, db: Session = Depends(get_db)):
    r = db.get(DailyReview, day)
    return row(r) if r else None


@router.put("/reviews/{day}")
def put_review(day: date, body: schemas.ReviewIn, db: Session = Depends(get_db)):
    tz_name = _tz(db)
    r = db.get(DailyReview, day) or DailyReview(day=day)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    db.add(r)
    at = to_utc_naive(datetime.combine(day, time(20, 0), tzinfo=get_zone(tz_name)))
    details = {"local_day": day.isoformat()}

    def sync_checkin(key: str, present: bool, **fields: Any) -> None:
        c = db.query(Checkin).filter_by(source_key=key).one_or_none()
        if present and c is None:
            db.add(Checkin(source_key=key, at=at, source="daily_review", details=details, **fields))
        elif present and c is not None:
            for k, v in fields.items():
                setattr(c, k, v)
        elif not present and c is not None:
            db.delete(c)

    for field, (domain, kind, title) in REVIEW_DERIVED.items():
        sync_checkin(f"review:{day}:{field}", getattr(r, field) is True, domain=domain, kind=kind, title=title)
    sync_checkin(f"review:{day}:learned", bool(r.learned.strip()), domain="learning", kind="checkpoint", title="What I learned", note=r.learned)
    sync_checkin(f"review:{day}:energy", r.energy is not None, domain="self", kind="energy", title="Energy", value=r.energy)
    db.commit()
    return row(r)


# ---- trading -----------------------------------------------------------------
@router.get("/trading/notes")
def list_trading_notes(days: int = 30, db: Session = Depends(get_db)):
    since = local_today(_tz(db)) - timedelta(days=days)
    return [row(n) for n in db.query(TradingNote).filter(TradingNote.day >= since).order_by(TradingNote.day.desc(), TradingNote.id.desc())]


@router.post("/trading/notes")
def create_trading_note(body: schemas.TradingNoteIn, db: Session = Depends(get_db)):
    data = body.model_dump()
    data["day"] = data["day"] or local_today(_tz(db))
    n = TradingNote(**data)
    db.add(n)
    db.commit()
    return row(n)


@router.delete("/trading/notes/{nid}")
def delete_trading_note(nid: int, db: Session = Depends(get_db)):
    n = db.get(TradingNote, nid)
    if not n:
        raise HTTPException(404)
    db.delete(n)
    db.commit()
    return {"deleted": nid}


@router.get("/trading/events")
def list_trading_events(days: int = 30, db: Session = Depends(get_db)):
    since = local_today(_tz(db)) - timedelta(days=days)
    return [row(e) for e in db.query(TradingEvent).filter(TradingEvent.activity_date >= since).order_by(TradingEvent.activity_date.desc()).limit(500)]


def trading_summary(db: Session, days: int) -> dict[str, Any]:
    today = local_today(_tz(db))
    since = today - timedelta(days=days)
    events = db.query(TradingEvent).filter(TradingEvent.activity_date >= since).all()
    trades = [e for e in events if e.trans_code in TRADE_CODES]
    notes = db.query(TradingNote).filter(TradingNote.day >= since).all()
    trade_days = {e.activity_date for e in trades}
    noted_days = {n.day for n in notes}
    fields = ["followed_plan", "risk_sized", "reason_recorded", "rules_followed", "intentional_time"]
    adherence = {}
    for f in fields:
        answered = [getattr(n, f) for n in notes if getattr(n, f) is not None]
        adherence[f] = {"yes": sum(1 for a in answered if a), "answered": len(answered)}
    return {
        "days": days,
        "trades": len(trades),
        "trade_days": len(trade_days),
        "notes": len(notes),
        "trade_days_with_notes": len(trade_days & noted_days),
        "process_adherence": adherence,
        "net_cash_flow": round(sum(e.amount or 0 for e in trades), 2),
        "data_notes": [
            "Process quality comes only from your notes — transaction history can't show plan adherence or risk sizing.",
            "Net cash flow is shown for context and is never used to judge trading quality.",
        ] + ([] if events else ["No Robinhood CSV imported for this period."]),
    }


@router.get("/trading/summary")
def get_trading_summary(days: int = 30, db: Session = Depends(get_db)):
    return trading_summary(db, days)


# ---- imports -----------------------------------------------------------------
@router.get("/imports")
def import_history(limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(ImportRun).filter(ImportRun.kind != "activitywatch")
    # Hide routine background scans that found nothing new.
    q = q.filter(~((ImportRun.kind == "music_scan") & (ImportRun.status == "ok") & (ImportRun.records_added == 0)))
    return [row(r) for r in q.order_by(ImportRun.started_at.desc()).limit(limit)]


@router.post("/imports/apple-health")
async def upload_apple_health(file: UploadFile = File(...), db: Session = Depends(get_db)):
    suffix = Path(file.filename or "export.zip").suffix.lower()
    if suffix not in {".zip", ".xml"}:
        raise HTTPException(400, "Upload the export.zip (or export.xml) from the Health app.")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp.flush()
        run = imp.import_apple_health(db, Path(tmp.name), file.filename)
    return row(run)


@router.post("/imports/apple-health/scan")
def scan_apple_health(db: Session = Depends(get_db)):
    folder = config.imports_dir / "apple_health"
    files = sorted([*folder.glob("*.zip"), *folder.glob("*.xml")], key=lambda p: p.stat().st_mtime)
    if not files:
        raise HTTPException(404, f"No export.zip/export.xml found in {folder}")
    return [row(imp.import_apple_health(db, files[-1]))]


@router.post("/imports/robinhood")
async def upload_robinhood(file: UploadFile = File(...), db: Session = Depends(get_db)):
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    return row(imp.import_robinhood_csv(db, text, file.filename or "robinhood.csv"))


@router.post("/imports/robinhood/scan")
def scan_robinhood(db: Session = Depends(get_db)):
    folder = config.imports_dir / "robinhood"
    runs = imp.scan_robinhood_folder(db, folder)
    return {"folder": str(folder), "runs": [row(r) for r in runs]}


@router.post("/imports/music/scan")
def scan_music(lookback_days: int = 30, db: Session = Depends(get_db)):
    return row(imp.scan_music(db, lookback_days))


@router.get("/music/signals")
def music_signals(days: int = 14, db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    return [row(m) for m in db.query(MusicSignal).filter(MusicSignal.at >= since).order_by(MusicSignal.at.desc()).limit(200)]


@router.post("/imports/summary")
def post_summary(body: schemas.SummaryIn, db: Session = Depends(get_db)):
    run = imp.ingest_summary(db, body.device_id, body.day, body.entries, body.note)
    if run.status == "error":
        raise HTTPException(400, run.error)
    return row(run)


# ---- scores, recommendations, recovery ---------------------------------------
@router.get("/scores")
def get_scores(day: date | None = None, db: Session = Depends(get_db)):
    day = day or local_today(_tz(db))
    return {"score": compute_score(db, day), "orchestration": compute_orchestration(db, day)}


@router.get("/recommendations")
def get_recommendations(db: Session = Depends(get_db)):
    return recommend(db)


@router.post("/recommendations/feedback")
def recommendation_feedback(body: schemas.FeedbackIn, db: Session = Depends(get_db)):
    snooze = utcnow() + timedelta(minutes=body.snooze_minutes or 30) if body.action == "snoozed" else None
    fb = RecommendationFeedback(rec_key=body.key, kind=body.kind, title=body.title, reason=body.reason, action=body.action, snooze_until=snooze)
    db.add(fb)
    db.commit()
    return row(fb)


@router.get("/recovery")
def get_recovery(db: Session = Depends(get_db)):
    return jsonify(current_assessment(db))


# ---- insights ----------------------------------------------------------------
@router.get("/insights")
def insights(days: int = 14, weeks: int = 6, db: Session = Depends(get_db)):
    s = get_settings(db)
    tz_name = s["timezone"]
    today = local_today(tz_name)
    first = today - timedelta(days=days - 1)
    lo, hi = local_range_bounds(first, today, tz_name)
    events = events_in_range(db, lo, min(hi, utcnow()))
    gap = timedelta(minutes=s["recovery"]["break_gap_minutes"])
    daily = []
    for i in range(days):
        d = first + timedelta(days=i)
        dlo, dhi = local_day_bounds(d, tz_name)
        dhi = min(dhi, utcnow())
        devs = [e for e in events if e.end_time > dlo and e.start_time < dhi]
        summ = category_summary(devs, dlo, dhi)
        comp = union([iv for e in devs if e.source in COMPUTER_SOURCES and (iv := event_interval(e, dlo, dhi))])
        stretches = continuous_stretches(comp, gap)
        review = db.get(DailyReview, d)
        daily.append({
            "day": d,
            "categories": {k: round(v["seconds"] / 60, 1) for k, v in summ["categories"].items()},
            "active_minutes": round(summ["active_computer_seconds"] / 60, 1),
            "longest_stretch_minutes": round(max(((e - s_).total_seconds() / 60 for s_, e in stretches), default=0), 1),
            "milestones": len(milestones_in_range(db, dlo, dhi)),
            "checkins": db.query(Checkin).filter(Checkin.at >= dlo, Checkin.at < dhi).count(),
            "energy": review.energy if review else None,
        })

    weekly = []
    for w in range(weeks - 1, -1, -1):
        wk = week_start(today) - timedelta(days=7 * w)
        end = min(wk + timedelta(days=6), today)
        sc = compute_score(db, end)
        weekly.append({"week_start": wk, "overall": sc["overall"], "dimensions": {d["key"]: d["score"] for d in sc["dimensions"]}})

    hm = db.query(HealthMetric).filter(HealthMetric.day >= first).all()
    by_metric: dict[str, list[float]] = defaultdict(list)
    for h in hm:
        by_metric[h.metric].append(h.value)
    health = {
        "workouts": len(by_metric.get("workout", [])),
        "avg_steps": round(sum(by_metric["steps"]) / len(by_metric["steps"])) if by_metric.get("steps") else None,
        "avg_sleep_hours": round(sum(by_metric["sleep_minutes"]) / len(by_metric["sleep_minutes"]) / 60, 1) if by_metric.get("sleep_minutes") else None,
        "avg_exercise_minutes": round(sum(by_metric["exercise_minutes"]) / len(by_metric["exercise_minutes"])) if by_metric.get("exercise_minutes") else None,
        "note": "Watch data is context, not a medical assessment.",
    }
    return {
        "days": daily,
        "weekly_scores": weekly,
        "orchestration": compute_orchestration(db, today),
        "trading": trading_summary(db, max(days, 30)),
        "health": health,
    }


# ---- settings ----------------------------------------------------------------
@router.get("/settings")
def read_settings(db: Session = Depends(get_db)):
    return {"settings": get_settings(db), "defaults": DEFAULT_SETTINGS}


@router.patch("/settings")
def patch_settings(patch: dict[str, Any], db: Session = Depends(get_db)):
    try:
        return {"settings": update_settings(db, patch)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---- privacy, status, export, deletion ---------------------------------------
@router.post("/privacy/pause")
def pause_collection(body: schemas.PauseIn, db: Session = Depends(get_db)):
    s = update_settings(db, {"privacy": {"collection_paused": body.paused}})
    return {"paused": s["privacy"]["collection_paused"]}


@router.get("/status")
def status(db: Session = Depends(get_db)):
    s = get_settings(db)
    aw = db.get(CollectorStatus, "activitywatch")
    return {
        "paused": s["privacy"]["collection_paused"],
        "timezone": s["timezone"],
        "data_dir": str(config.home),
        "db_path": str(config.db_path),
        "activitywatch": {"enabled": s["activitywatch"]["enabled"], **(row(aw) if aw else {})},
        "counts": {
            "activity_events": db.query(ActivityEvent).count(),
            "health_metrics": db.query(HealthMetric).count(),
            "trading_events": db.query(TradingEvent).count(),
            "music_signals": db.query(MusicSignal).count(),
            "sessions": db.query(ClaudeSession).count(),
            "checkins": db.query(Checkin).count(),
        },
        "onboarding_complete": s["preferences"]["onboarding_complete"],
    }


@router.get("/export")
def export_all(db: Session = Depends(get_db)):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in Base.metadata.sorted_tables:
            rows = [dict(r._mapping) for r in db.execute(table.select())]
            zf.writestr(f"{table.name}.json", json.dumps(jsonify(rows), indent=1, default=str))
    buf.seek(0)
    name = f"lifeos-export-{local_today(_tz(db)).isoformat()}.zip"
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


DELETE_SCOPES = {
    "activity": [ActivityEvent],
    "health": [HealthMetric],
    "trading": [TradingEvent, TradingNote],
    "music": [MusicSignal],
    "sessions": [SessionStateChange, ClaudeSession],
    "reviews": [DailyReview, Checkin],
    "recommendations": [RecommendationFeedback],
}


@router.delete("/data/{scope}")
def delete_data(scope: str, confirm: str = "", db: Session = Depends(get_db)):
    if confirm != "DELETE":
        raise HTTPException(400, "Pass confirm=DELETE to permanently delete data.")
    scopes = list(DELETE_SCOPES) if scope == "all" else [scope]
    if any(s_ not in DELETE_SCOPES for s_ in scopes):
        raise HTTPException(400, f"Unknown scope. Use one of: {', '.join(DELETE_SCOPES)}, all")
    deleted: dict[str, int] = {}
    for s_ in scopes:
        for model in DELETE_SCOPES[s_]:
            deleted[model.__tablename__] = db.query(model).delete()
    if "activity" in scopes:
        aw = db.get(CollectorStatus, "activitywatch")
        if aw:
            aw.synced_until = None
    db.commit()
    return {"deleted": deleted}
