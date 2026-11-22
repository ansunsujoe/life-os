"""Activity event storage, dedup, and aggregation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from lifeos.models import ActivityCategory, ActivityEvent, Device
from lifeos.services.classification import Classifier, enrich, load_classifier
from lifeos.services.intervals import Interval, clip, total_seconds, union

CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
COMPUTER_SOURCES = {"activitywatch", "manual_summary", "activity_json"}


@dataclass
class NormalizedEvent:
    source_key: str
    source: str
    start_time: datetime
    end_time: datetime
    device_id: str | None = None
    app: str | None = None
    title: str | None = None
    domain: str | None = None
    activity: str | None = None
    category: str | None = None  # None → classify with rules
    confidence: str | None = None
    subcategory: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class UpsertResult:
    added: int = 0
    updated: int = 0
    skipped: int = 0


class IngestRejected(Exception):
    pass


def check_device_allowed(device: Device | None, *, aggregate: bool = False) -> None:
    """Enforce per-device privacy policy before accepting any data."""
    if device is None:
        raise IngestRejected("Unknown device. Register it under Sources first.")
    if not device.collection_enabled:
        raise IngestRejected(f"Collection is disabled for device '{device.id}'.")
    if device.is_work and not device.monitoring_approved and not aggregate:
        raise IngestRejected(
            f"Device '{device.id}' is a work device without monitoring approval. "
            "Only user-entered aggregate summaries are accepted."
        )


# Evidence keys a content-free (work) device may keep: none of them can hold text.
CONTENT_FREE_EVIDENCE = {"aggregate", "explicit_category", "afk_filtered", "minutes", "pattern"}


def _allowed_subcategories(db_session) -> set[str]:
    from lifeos.models import ClassificationRule
    from lifeos.services.classification import TOPIC_SUBCATEGORY

    subs = {r.subcategory for r in db_session.query(ClassificationRule) if r.subcategory}
    subs |= set(TOPIC_SUBCATEGORY.values()) | {
        "Short-form video", "Browsing video feed", "Watching videos", "Streaming", "Social media", "Social feed", "News",
        "Quick hopping", "Topic video",
    }
    return subs


def _apply(ev: ActivityEvent, n: NormalizedEvent, clf: Classifier | None, store_titles: bool, aggregate_only: bool,
           allowed_subs: set[str] | None = None) -> None:
    if aggregate_only:
        _apply_content_free(ev, n, allowed_subs or set())
        return
    app, domain, evidence = enrich(n.app, n.title, n.domain, n.evidence)
    if not store_titles:
        evidence.pop("project", None)  # derived from the title
    if n.category is None:
        c = (clf or Classifier([])).classify(app, n.title, domain, evidence.get("url_kind"))
        category, confidence, rule_id, label, sub = c.category, c.confidence, c.rule_id, c.label, c.subcategory
    else:
        category, confidence, rule_id, label, sub = n.category, n.confidence or "high", None, n.activity or n.category, n.subcategory
    ev.source = n.source
    ev.device_id = n.device_id
    ev.start_time = n.start_time
    ev.end_time = n.end_time
    ev.category_key = category
    ev.subcategory = sub
    ev.confidence = confidence
    ev.rule_id = rule_id
    ev.activity = n.activity or label
    if aggregate_only:
        ev.app = ev.title = ev.domain = None
        ev.activity = n.activity or category
    else:
        ev.app = app
        ev.domain = domain
        ev.title = n.title if store_titles else None
    if aggregate_only:
        evidence = {k: v for k, v in evidence.items() if k not in {"project", "url_kind", "domain_from_title", "url"}}
    ev.evidence = {**evidence, **({"explicit_category": True} if n.category is not None else {})}


def _apply_content_free(ev: ActivityEvent, n: NormalizedEvent, allowed_subs: set[str]) -> None:
    """Store only category, a known generic subcategory, times and confidence.
    Anything else the sender included is discarded here, on the hub."""
    category = n.category or "other"
    sub = n.subcategory if n.subcategory in allowed_subs else None
    ev.source = n.source
    ev.device_id = n.device_id
    ev.start_time, ev.end_time = n.start_time, n.end_time
    ev.category_key = category
    ev.subcategory = sub
    ev.confidence = n.confidence if n.confidence in {"high", "medium", "low"} else "low"
    ev.rule_id = None
    ev.app = ev.title = ev.domain = None
    ev.activity = sub or category
    ev.evidence = {k: v for k, v in (n.evidence or {}).items() if k in CONTENT_FREE_EVIDENCE and isinstance(v, bool | int | float)}
    ev.evidence.update({"aggregate": True, "explicit_category": True})


def upsert_events(
    db: Session,
    events: list[NormalizedEvent],
    *,
    import_id: int | None = None,
    store_titles: bool = True,
    classifier: Classifier | None = None,
    commit: bool = True,
) -> UpsertResult:
    """Insert or update by `source_key`. User corrections are preserved."""
    res = UpsertResult()
    if not events:
        return res
    clf = classifier or load_classifier(db)
    devices = {d.id: d for d in db.query(Device).all()}
    allowed_subs = _allowed_subcategories(db) if any(d.content_free for d in devices.values()) else set()
    known_cats = {c for (c,) in db.query(ActivityCategory.key)}
    keys = [e.source_key for e in events]
    existing: dict[str, ActivityEvent] = {}
    for i in range(0, len(keys), 500):
        for row in db.query(ActivityEvent).filter(ActivityEvent.source_key.in_(keys[i : i + 500])):
            existing[row.source_key] = row
    seen: set[str] = set()
    for n in events:
        if n.end_time < n.start_time or n.source_key in seen:
            res.skipped += 1
            continue
        seen.add(n.source_key)
        dev = devices.get(n.device_id) if n.device_id else None
        titles = store_titles and (dev.store_titles if dev else True) and not (dev and dev.is_work)
        aggregate_only = bool(dev and dev.content_free)
        if aggregate_only and n.category not in known_cats:
            n.category = "other"
        row = existing.get(n.source_key)
        if row is None:
            row = ActivityEvent(source_key=n.source_key, import_id=import_id)
            _apply(row, n, clf, titles, aggregate_only, allowed_subs)
            db.add(row)
            res.added += 1
        else:
            before = (row.start_time, row.end_time, row.category_key, row.app, row.title, row.domain)
            _apply(row, n, clf, titles, aggregate_only, allowed_subs)
            after = (row.start_time, row.end_time, row.category_key, row.app, row.title, row.domain)
            if before != after:
                res.updated += 1
            else:
                res.skipped += 1
    if commit:
        db.commit()
    return res


def events_in_range(
    db: Session, start: datetime, end: datetime, *, include_excluded: bool = False, sources: set[str] | None = None
) -> list[ActivityEvent]:
    q = db.query(ActivityEvent).filter(ActivityEvent.start_time < end, ActivityEvent.end_time > start)
    if not include_excluded:
        q = q.filter(ActivityEvent.excluded.is_(False))
    if sources:
        q = q.filter(ActivityEvent.source.in_(sources))
    return q.order_by(ActivityEvent.start_time).all()


def event_interval(ev: ActivityEvent, lo: datetime, hi: datetime) -> Interval | None:
    return clip((ev.start_time, ev.end_time), lo, hi)


@dataclass
class Block:
    start: datetime
    end: datetime
    category: str
    device_id: str | None
    source: str
    seconds: float
    confidence: str
    activities: list[tuple[str, float]]
    event_ids: list[int]
    confirmed: bool


def timeline_blocks(events: list[ActivityEvent], lo: datetime, hi: datetime, merge_gap: timedelta) -> list[Block]:
    """Merge consecutive same-category events into readable timeline blocks."""
    groups: list[list[tuple[ActivityEvent, Interval]]] = []
    for ev in sorted(events, key=lambda e: (e.start_time, e.id or 0)):
        iv = event_interval(ev, lo, hi)
        if iv is None:
            continue
        if groups:
            last_ev, last_iv = groups[-1][-1]
            gstart = groups[-1][0][1][0]
            gend = max(x[1][1] for x in groups[-1])
            if (
                last_ev.effective_category == ev.effective_category
                and last_ev.device_id == ev.device_id
                and last_ev.source == ev.source
                and iv[0] - gend <= merge_gap
                and iv[0] >= gstart
            ):
                groups[-1].append((ev, iv))
                continue
        groups.append([(ev, iv)])

    blocks: list[Block] = []
    for g in groups:
        ivs = [iv for _, iv in g]
        secs = total_seconds(ivs)
        conf_secs: dict[str, float] = defaultdict(float)
        acts: dict[str, float] = defaultdict(float)
        for ev, iv in g:
            d = (iv[1] - iv[0]).total_seconds()
            conf_secs[ev.effective_confidence] += d
            acts[ev.activity or ev.app or "Unknown"] += d
        dominant = max(conf_secs.items(), key=lambda kv: (kv[1], CONFIDENCE_RANK[kv[0]]))[0] if conf_secs else "low"
        first = g[0][0]
        blocks.append(
            Block(
                start=min(iv[0] for iv in ivs),
                end=max(iv[1] for iv in ivs),
                category=first.effective_category,
                device_id=first.device_id,
                source=first.source,
                seconds=secs,
                confidence=dominant,
                activities=sorted(acts.items(), key=lambda kv: -kv[1])[:5],
                event_ids=[ev.id for ev, _ in g],
                confirmed=all(ev.confirmed or ev.category_override for ev, _ in g),
            )
        )
    return blocks


def category_summary(events: list[ActivityEvent], lo: datetime, hi: datetime) -> dict[str, Any]:
    """Per-category totals. Overlapping events within a category count once."""
    by_cat: dict[str, list[Interval]] = defaultdict(list)
    by_cat_dev: dict[tuple[str, str], list[Interval]] = defaultdict(list)
    by_cat_conf: dict[tuple[str, str], list[Interval]] = defaultdict(list)
    by_cat_src: dict[tuple[str, str], list[Interval]] = defaultdict(list)
    by_cat_sub: dict[tuple[str, str], list[Interval]] = defaultdict(list)
    computer: list[Interval] = []
    for ev in events:
        iv = event_interval(ev, lo, hi)
        if iv is None:
            continue
        cat = ev.effective_category
        by_cat[cat].append(iv)
        by_cat_dev[(cat, ev.device_id or "unknown")].append(iv)
        by_cat_conf[(cat, ev.effective_confidence)].append(iv)
        by_cat_src[(cat, ev.source)].append(iv)
        by_cat_sub[(cat, ev.effective_subcategory or "General")].append(iv)
        if ev.source in COMPUTER_SOURCES:
            computer.append(iv)

    cats: dict[str, Any] = {}
    for cat, ivs in by_cat.items():
        cats[cat] = {
            "seconds": total_seconds(ivs),
            "by_device": {d: total_seconds(v) for (c, d), v in by_cat_dev.items() if c == cat},
            "by_confidence": {k: total_seconds(v) for (c, k), v in by_cat_conf.items() if c == cat},
            "by_source": {s: total_seconds(v) for (c, s), v in by_cat_src.items() if c == cat},
            "by_subcategory": dict(sorted(((s, total_seconds(v)) for (c, s), v in by_cat_sub.items() if c == cat), key=lambda kv: -kv[1])),
        }
    return {"categories": cats, "active_computer_seconds": total_seconds(computer)}


def active_intervals(db: Session, start: datetime, end: datetime) -> list[Interval]:
    """Union of non-excluded computer activity in range (for recovery signals)."""
    evs = events_in_range(db, start, end, sources=COMPUTER_SOURCES)
    return union([iv for ev in evs if (iv := event_interval(ev, start, end))])


def find_events_by_ids(db: Session, ids: list[int]) -> list[ActivityEvent]:
    return db.query(ActivityEvent).filter(ActivityEvent.id.in_(ids)).all() if ids else []


def search_events(db: Session, start: datetime, end: datetime, query: str | None, category: str | None) -> list[ActivityEvent]:
    q = db.query(ActivityEvent).filter(ActivityEvent.start_time < end, ActivityEvent.end_time > start)
    if category:
        q = q.filter(func.coalesce(ActivityEvent.category_override, ActivityEvent.pattern_category, ActivityEvent.category_key) == category)
    if query:
        like = f"%{query}%"
        q = q.filter(or_(ActivityEvent.app.ilike(like), ActivityEvent.title.ilike(like), ActivityEvent.domain.ilike(like), ActivityEvent.activity.ilike(like)))
    return q.order_by(ActivityEvent.start_time).limit(2000).all()
