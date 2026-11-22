"""ActivityWatch ingestion via its local REST API (http://localhost:5600/api/0).

ActivityWatch data is *evidence of computer activity*, not proof of progress.

Approach: for each local calendar day touched since the last sync, fetch that
day's window / AFK / web-tab events, keep only window time that overlaps
not-AFK periods, attach the browser domain from web-tab buckets, then upsert
with deterministic keys `aw:{bucket}:{day}:{event_id}:{piece}`. Re-processing a
whole day makes the result stable even as AW extends in-progress events via
heartbeats, and lets stale pieces be removed. User corrections carry over.
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from lifeos.models import ActivityEvent, CollectorStatus, Device, ImportRun
from lifeos.services.activity import NormalizedEvent, upsert_events
from lifeos.services.classification import domain_from_url, is_away_app, is_browser, load_classifier, normalize_app, url_kind
from lifeos.services.intervals import Interval, intersect
from lifeos.services.patterns import apply_patterns
from lifeos.services.settings import get_settings
from lifeos.seed import detect_local_device_id
from lifeos.timeutil import local_day_bounds, parse_iso, to_local, utcnow

log = logging.getLogger("lifeos.activitywatch")


@dataclass
class AWEvent:
    id: int | str
    start: datetime
    end: datetime
    data: dict[str, Any]


def parse_aw_events(raw: list[dict[str, Any]]) -> list[AWEvent]:
    out = []
    for e in raw:
        try:
            start = parse_iso(e["timestamp"])
            end = start + timedelta(seconds=float(e.get("duration", 0) or 0))
        except (KeyError, ValueError, TypeError):
            continue
        out.append(AWEvent(id=e.get("id", f"{e.get('timestamp')}"), start=start, end=end, data=e.get("data") or {}))
    return out


def not_afk_intervals(afk_events: list[AWEvent]) -> list[Interval]:
    return [(e.start, e.end) for e in afk_events if e.data.get("status") == "not-afk" and e.end > e.start]


class WebIndex:
    """Find the browser tab most overlapping a time interval."""

    def __init__(self, web_events: list[AWEvent]):
        self.events = sorted(web_events, key=lambda e: e.start)
        self.starts = [e.start for e in self.events]

    def best(self, s: datetime, e: datetime) -> AWEvent | None:
        i = bisect.bisect_right(self.starts, e)
        best, best_ov = None, 0.0
        # Walk back a bounded number of candidates (tab events are short and sorted).
        for j in range(i - 1, max(-1, i - 200), -1):
            w = self.events[j]
            ov = (min(e, w.end) - max(s, w.start)).total_seconds()
            if ov > best_ov:
                best, best_ov = w, ov
            if w.end < s and (s - w.end) > timedelta(hours=2):
                break
        return best


def build_day_events(
    *,
    bucket_id: str,
    device_id: str,
    day: date,
    day_bounds: Interval,
    window_events: list[AWEvent],
    afk_events: list[AWEvent] | None,
    web_events: list[AWEvent],
    store_full_urls: bool,
) -> list[NormalizedEvent]:
    """Pure transformation: AW events for one day → normalized activity events."""
    lo, hi = day_bounds
    active = not_afk_intervals(afk_events) if afk_events is not None else None
    web = WebIndex(web_events)
    out: list[NormalizedEvent] = []
    for we in window_events:
        s, e = max(we.start, lo), min(we.end, hi)
        if e <= s:
            continue
        pieces = intersect([(s, e)], active) if active is not None else [(s, e)]
        app = normalize_app(we.data.get("app"))
        title = (we.data.get("title") or "").strip() or None
        if is_away_app(app):
            continue  # lock screen / screensaver: away, not activity
        for idx, (ps, pe) in enumerate(pieces):
            if (pe - ps).total_seconds() < 1:
                continue
            domain = None
            evidence: dict[str, Any] = {"aw_bucket": bucket_id, "aw_event_id": we.id, "afk_filtered": active is not None}
            if is_browser(app):
                tab = web.best(ps, pe)
                if tab:
                    url = tab.data.get("url")
                    domain = domain_from_url(url)
                    if store_full_urls and url:
                        evidence["url"] = url
                    if url:
                        kind = url_kind(url, domain)
                        if kind:
                            evidence["url_kind"] = kind
                    if tab.data.get("incognito"):
                        # Never keep anything from private browsing beyond the fact it happened.
                        domain, title = None, None
                        evidence.pop("url", None)
                        evidence.pop("url_kind", None)
                        evidence["incognito"] = True
            out.append(
                NormalizedEvent(
                    source_key=f"aw:{bucket_id}:{day.isoformat()}:{we.id}:{idx}",
                    source="activitywatch",
                    device_id=device_id,
                    start_time=ps,
                    end_time=pe,
                    app=app,
                    title=title,
                    domain=domain,
                    evidence=evidence,
                )
            )
    return out


class AWClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base = base_url.rstrip("/") + "/api/0"
        self.http = httpx.Client(timeout=timeout)

    def info(self) -> dict[str, Any]:
        r = self.http.get(f"{self.base}/info")
        r.raise_for_status()
        return r.json()

    def buckets(self) -> dict[str, dict[str, Any]]:
        r = self.http.get(f"{self.base}/buckets/")
        r.raise_for_status()
        return r.json()

    def events(self, bucket_id: str, start: datetime, end: datetime) -> list[AWEvent]:
        params = {"start": start.isoformat() + "Z", "end": end.isoformat() + "Z", "limit": -1}
        r = self.http.get(f"{self.base}/buckets/{bucket_id}/events", params=params)
        r.raise_for_status()
        return parse_aw_events(r.json())

    def close(self) -> None:
        self.http.close()


def _slug(host: str) -> str:
    import re

    return re.sub(r"[^a-z0-9-]+", "-", host.split(".")[0].lower()).strip("-") or "unknown"


def _resolve_device(db: Session, hostname: str) -> Device:
    """Map an AW hostname to a device. Unknown hosts are registered *disabled* so
    nothing from them is ingested until the user approves it under Sources."""
    dev_id = _slug(hostname)
    dev = db.get(Device, dev_id)
    if dev:
        return dev
    local = detect_local_device_id()
    if dev_id == local:
        dev = Device(id=dev_id, name="Personal Mac", kind="mac", monitoring_approved=True)
    else:
        dev = Device(
            id=dev_id, name=hostname, kind="other", is_work=True, monitoring_approved=False,
            collection_enabled=False, store_titles=False, aggregate_only=True,
        )
    db.add(dev)
    db.commit()
    return dev


def _replace_day(db: Session, bucket_id: str, day: date, new_events: list[NormalizedEvent], store_titles: bool, import_id: int, clf) -> tuple[int, int, int]:
    """Upsert one day's events for a bucket; delete stale pieces; carry corrections."""
    prefix = f"aw:{bucket_id}:{day.isoformat()}:"
    existing = db.query(ActivityEvent).filter(ActivityEvent.source_key.like(prefix + "%")).all()
    corrections: dict[str, tuple[str | None, bool, bool]] = {}
    for row in existing:
        if row.category_override or row.excluded or row.confirmed:
            ev_id = row.source_key[len(prefix) :].rsplit(":", 1)[0]
            corrections[ev_id] = (row.category_override, row.excluded, row.confirmed)
    new_keys = {n.source_key for n in new_events}
    removed = 0
    for row in existing:
        if row.source_key not in new_keys:
            db.delete(row)
            removed += 1
    db.flush()
    res = upsert_events(db, new_events, import_id=import_id, store_titles=store_titles, classifier=clf, commit=False)
    if corrections:
        rows = db.query(ActivityEvent).filter(ActivityEvent.source_key.like(prefix + "%")).all()
        for row in rows:
            ev_id = row.source_key[len(prefix) :].rsplit(":", 1)[0]
            if ev_id in corrections:
                ov, ex, cf = corrections[ev_id]
                row.category_override = row.category_override or ov
                row.excluded = row.excluded or ex
                row.confirmed = row.confirmed or cf
    db.commit()
    return res.added, res.updated, removed


def sync_activitywatch(db: Session, *, client: AWClient | None = None, days: list[date] | None = None) -> dict[str, Any]:
    settings = get_settings(db)
    aw_cfg, privacy, tz_name = settings["activitywatch"], settings["privacy"], settings["timezone"]
    status = db.get(CollectorStatus, "activitywatch") or CollectorStatus(key="activitywatch")
    db.add(status)
    status.last_run_at = utcnow()

    if privacy.get("collection_paused") or not aw_cfg.get("enabled") or not status.enabled:
        status.last_error = None
        db.commit()
        return {"status": "paused", "message": "ActivityWatch collection is paused or disabled."}

    own_client = client is None
    client = client or AWClient(aw_cfg["url"])
    run = ImportRun(kind="activitywatch", filename=aw_cfg["url"])
    db.add(run)
    db.commit()
    try:
        buckets = client.buckets()
        now = utcnow()
        if days is None:
            since = status.synced_until or (now - timedelta(hours=aw_cfg["first_sync_lookback_hours"]))
            since -= timedelta(hours=1)  # AFK status is often finalised late
            d0, d1 = to_local(since, tz_name).date(), to_local(now, tz_name).date()
            days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]

        by_host: dict[str, dict[str, list[str]]] = {}
        for bid, meta in buckets.items():
            host = meta.get("hostname") or "unknown"
            btype = meta.get("type", "")
            kind = "window" if btype == "currentwindow" else "afk" if btype == "afkstatus" else "web" if btype.startswith("web.tab") else None
            if kind:
                by_host.setdefault(host, {}).setdefault(kind, []).append(bid)

        clf = load_classifier(db)
        added = updated = removed = 0
        skipped_hosts = []
        for host, kinds in by_host.items():
            dev = _resolve_device(db, host)
            if not dev.collection_enabled or (dev.is_work and not dev.monitoring_approved):
                skipped_hosts.append(dev.id)
                continue
            store_titles = privacy["store_window_titles"] and dev.store_titles and not dev.is_work
            for day in days:
                lo, hi = local_day_bounds(day, tz_name)
                hi_eff = min(hi, now)
                if hi_eff <= lo:
                    continue
                afk = None
                if kinds.get("afk"):
                    afk = [e for b in kinds["afk"] for e in client.events(b, lo, hi_eff)]
                web = [e for b in kinds.get("web", []) for e in client.events(b, lo, hi_eff)]
                for wb in kinds.get("window", []):
                    win = client.events(wb, lo, hi_eff)
                    evs = build_day_events(
                        bucket_id=wb, device_id=dev.id, day=day, day_bounds=(lo, hi_eff),
                        window_events=win, afk_events=afk, web_events=web,
                        store_full_urls=privacy["store_full_urls"],
                    )
                    a, u, r = _replace_day(db, wb, day, evs, store_titles, run.id, clf)
                    added, updated, removed = added + a, updated + u, removed + r
                    run.records_seen += len(win)
                apply_patterns(db, lo, hi_eff)

        run.records_added, run.records_updated, run.records_skipped = added, updated, removed
        run.status, run.finished_at = "ok", utcnow()
        status.synced_until, status.last_ok_at, status.last_error = now, now, None
        status.details = {"hosts": list(by_host), "skipped_devices": skipped_hosts, "days": [d.isoformat() for d in days]}
        db.commit()
        return {"status": "ok", "added": added, "updated": updated, "removed": removed, "skipped_devices": skipped_hosts}
    except httpx.HTTPError as exc:
        msg = f"Could not reach ActivityWatch at {aw_cfg['url']} ({type(exc).__name__}). Is aw-server running?"
        run.status, run.error, run.finished_at = "error", msg, utcnow()
        status.last_error = msg
        db.commit()
        return {"status": "error", "message": msg}
    except Exception as exc:  # noqa: BLE001 — record a sanitised error, never raw data
        log.exception("ActivityWatch sync failed")
        msg = f"ActivityWatch sync failed: {type(exc).__name__}"
        run.status, run.error, run.finished_at = "error", msg, utcnow()
        status.last_error = msg
        db.commit()
        return {"status": "error", "message": msg}
    finally:
        if own_client:
            client.close()


def aw_probe(url: str) -> dict[str, Any]:
    c = AWClient(url, timeout=2.0)
    try:
        info = c.info()
        buckets = c.buckets()
        return {"reachable": True, "version": info.get("version"), "hostname": info.get("hostname"), "buckets": [
            {"id": k, "type": v.get("type"), "hostname": v.get("hostname")} for k, v in buckets.items()
        ]}
    except httpx.HTTPError:
        return {"reachable": False}
    finally:
        c.close()
