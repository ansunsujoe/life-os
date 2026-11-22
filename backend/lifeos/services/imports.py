"""Import workflows that write to the database, with import history."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from lifeos.importers import apple_health, music, robinhood
from lifeos.models import Device, HealthMetric, ImportRun, MusicSignal, TradingEvent
from lifeos.services.activity import IngestRejected, NormalizedEvent, check_device_allowed, upsert_events
from lifeos.services.settings import get_settings
from lifeos.timeutil import get_zone, local_day_bounds, local_today, parse_iso, to_local, to_utc_naive, utcnow

log = logging.getLogger("lifeos.imports")


def _start(db: Session, kind: str, filename: str | None = None, device_id: str | None = None) -> ImportRun:
    run = ImportRun(kind=kind, filename=filename, device_id=device_id)
    db.add(run)
    db.commit()
    return run


def _finish(db: Session, run: ImportRun, *, error: str | None = None) -> ImportRun:
    run.finished_at = utcnow()
    run.status = "error" if error else "ok"
    run.error = error
    db.commit()
    return run


def _fail(db: Session, run: ImportRun, exc: Exception, label: str) -> ImportRun:
    db.rollback()
    # ValueError messages are written by us; anything else gets only its type name
    # so raw source contents never land in logs or the UI (spec §11.5).
    msg = str(exc) if isinstance(exc, ValueError | IngestRejected) else f"{label} failed ({type(exc).__name__})"
    log.warning("%s import failed: %s", label, type(exc).__name__)
    return _finish(db, run, error=msg)


# ---- Apple Health ------------------------------------------------------------


def import_apple_health(db: Session, path: Path, display_name: str | None = None) -> ImportRun:
    s = get_settings(db)
    tz_name = s["timezone"]
    run = _start(db, "apple_health", display_name or path.name)
    try:
        since = local_today(tz_name) - timedelta(days=s["apple_health"]["lookback_days"])
        summary = apple_health.parse_export(path, tz_name, since=since)
        run.records_seen = summary.records_seen + len(summary.workouts)
        added = updated = 0

        def upsert_metric(key: str, **fields: Any) -> None:
            nonlocal added, updated
            row = db.query(HealthMetric).filter_by(source_key=key).one_or_none()
            if row is None:
                db.add(HealthMetric(source_key=key, import_id=run.id, **fields))
                added += 1
            elif row.value != fields["value"]:
                for k, v in fields.items():
                    setattr(row, k, v)
                updated += 1

        workout_events = []
        for w in summary.workouts:
            key = f"ah:workout:{w['start'].isoformat()}:{w['type']}"
            upsert_metric(key, metric="workout", start_time=w["start"], end_time=w["end"], value=w["minutes"], unit="min",
                          day=to_local(w["start"], tz_name).date(), details={"type": w["type"], "energy_kcal": w["energy_kcal"]})
            workout_events.append(NormalizedEvent(
                source_key=key, source="apple_health", start_time=w["start"], end_time=w["end"],
                category="health", confidence="high", activity=f"Workout: {w['type']}",
                evidence={"minutes": w["minutes"], "energy_kcal": w["energy_kcal"]},
            ))
        for (metric, day), value in summary.daily.items():
            lo, hi = local_day_bounds(day, tz_name)
            unit = {"steps": "count", "exercise_minutes": "min", "active_energy": "kcal"}[metric]
            upsert_metric(f"ah:{metric}:{day.isoformat()}", metric=metric, day=day, start_time=lo, end_time=hi, value=round(value, 1), unit=unit)
        for day, minutes in summary.sleep_minutes.items():
            lo, hi = local_day_bounds(day, tz_name)
            upsert_metric(f"ah:sleep:{day.isoformat()}", metric="sleep_minutes", day=day, start_time=lo, end_time=hi, value=round(minutes, 1), unit="min")
        db.commit()
        upsert_events(db, workout_events, import_id=run.id)
        run.records_added, run.records_updated = added, updated
        return _finish(db, run)
    except Exception as exc:  # noqa: BLE001
        return _fail(db, run, exc, "Apple Health")


# ---- Robinhood ---------------------------------------------------------------


def import_robinhood_csv(db: Session, text: str, filename: str) -> ImportRun:
    run = _start(db, "robinhood_csv", filename)
    try:
        rows, skipped = robinhood.parse_csv(text)
        run.records_seen = len(rows) + skipped
        keys = {r.source_key for r in rows}
        existing = {k for (k,) in db.query(TradingEvent.source_key).filter(TradingEvent.source_key.in_(keys))} if keys else set()
        added = 0
        for r in rows:
            if r.source_key in existing:
                skipped += 1
                continue
            db.add(TradingEvent(
                source_key=r.source_key, activity_date=r.activity_date, settle_date=r.settle_date, instrument=r.instrument,
                description=r.description, trans_code=r.trans_code, quantity=r.quantity, price=r.price, amount=r.amount, import_id=run.id,
            ))
            added += 1
        run.records_added, run.records_skipped = added, skipped
        db.commit()
        return _finish(db, run)
    except Exception as exc:  # noqa: BLE001
        return _fail(db, run, exc, "Robinhood CSV")


def scan_robinhood_folder(db: Session, folder: Path) -> list[ImportRun]:
    done = {r.filename for r in db.query(ImportRun).filter_by(kind="robinhood_csv", status="ok")}
    runs = []
    for f in sorted(folder.glob("*.csv")):
        if f.name in done:
            continue
        runs.append(import_robinhood_csv(db, f.read_text(encoding="utf-8-sig", errors="replace"), f.name))
    return runs


# ---- Music -------------------------------------------------------------------


def scan_music(db: Session, lookback_days: int = 30) -> ImportRun:
    s = get_settings(db)["music"]
    run = _start(db, "music_scan", ", ".join(s["project_dirs"]))
    try:
        signals = music.scan_dirs(s["project_dirs"], s["bounce_extensions"], since=utcnow() - timedelta(days=lookback_days))
        run.records_seen = len(signals)
        keys = [x.source_key for x in signals]
        existing = {k for (k,) in db.query(MusicSignal.source_key).filter(MusicSignal.source_key.in_(keys))} if keys else set()
        for x in signals:
            if x.source_key not in existing:
                db.add(MusicSignal(source_key=x.source_key, project_name=x.project_name, path=x.path, kind=x.kind, at=x.at))
                run.records_added += 1
        run.records_skipped = len(signals) - run.records_added
        db.commit()
        return _finish(db, run)
    except Exception as exc:  # noqa: BLE001
        return _fail(db, run, exc, "Music scan")


# ---- Generic activity / work-device summaries --------------------------------


def _parse_event_dict(d: dict[str, Any], device_id: str, i: int, prefix: str) -> NormalizedEvent:
    start = parse_iso(str(d["start_time"]))
    end = parse_iso(str(d["end_time"]))
    key = d.get("source_key") or f"{prefix}:{device_id}:{start.isoformat()}:{d.get('category') or d.get('app') or i}"
    return NormalizedEvent(
        source_key=str(key), source=d.get("source") or "activity_json", device_id=device_id, start_time=start, end_time=end,
        app=d.get("app"), title=d.get("title"), domain=d.get("domain"), activity=d.get("activity"),
        category=d.get("category"), confidence=d.get("confidence"), evidence=d.get("evidence") or {},
    )


def ingest_events(db: Session, device_id: str, raw_events: list[dict[str, Any]], filename: str | None = None) -> ImportRun:
    run = _start(db, "activity_json", filename, device_id)
    try:
        if get_settings(db)["privacy"]["collection_paused"]:
            raise ValueError("Collection is paused.")
        aggregate = all(e.get("category") and not (e.get("app") or e.get("title") or e.get("domain")) for e in raw_events)
        check_device_allowed(db.get(Device, device_id), aggregate=aggregate)
        events = [_parse_event_dict(e, device_id, i, "import") for i, e in enumerate(raw_events)]
        run.records_seen = len(events)
        res = upsert_events(db, events, import_id=run.id)
        run.records_added, run.records_updated, run.records_skipped = res.added, res.updated, res.skipped
        return _finish(db, run)
    except (KeyError, TypeError) as exc:
        return _fail(db, run, ValueError(f"Malformed event: missing or invalid field {exc}"), "Activity import")
    except Exception as exc:  # noqa: BLE001
        return _fail(db, run, exc, "Activity import")


def parse_activity_file(name: str, content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig", errors="replace")
    if name.lower().endswith(".json"):
        data = json.loads(text)
        return data["events"] if isinstance(data, dict) else data
    return list(csv.DictReader(io.StringIO(text)))


def ingest_summary(db: Session, device_id: str, day: date, entries: list[dict[str, Any]], note: str = "") -> ImportRun:
    """User-entered aggregate summary (e.g., a work computer that must stay unmonitored).

    Events are laid end-to-end from 09:00 local purely so they can be drawn;
    they carry `evidence.aggregate = true` and no app/title data."""
    tz_name = get_settings(db)["timezone"]
    run = _start(db, "manual_summary", f"{device_id} {day.isoformat()}", device_id)
    try:
        check_device_allowed(db.get(Device, device_id), aggregate=True)
        cursor = to_utc_naive(datetime.combine(day, time(9, 0), tzinfo=get_zone(tz_name)))
        events = []
        for e in entries:
            minutes = float(e.get("minutes") or 0)
            if minutes <= 0:
                continue
            end = cursor + timedelta(minutes=minutes)
            events.append(NormalizedEvent(
                source_key=f"summary:{device_id}:{day.isoformat()}:{e['category']}", source="manual_summary", device_id=device_id,
                start_time=cursor, end_time=end, category=e["category"], confidence="high",
                activity=e.get("label") or f"{e['category']} (summary)", evidence={"aggregate": True, "minutes": minutes, "note": note},
            ))
            cursor = end
        run.records_seen = len(events)
        res = upsert_events(db, events, import_id=run.id)
        run.records_added, run.records_updated = res.added, res.updated
        return _finish(db, run)
    except Exception as exc:  # noqa: BLE001
        return _fail(db, run, exc, "Summary")
