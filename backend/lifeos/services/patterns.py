"""Sequence-level understanding of activity.

Single events say little ("Chrome, 40 seconds"). Sequences say a lot:

* **Drift detection** — a run of leisure/feed activity that hops quickly between
  many short items (shorts, feeds, one clip after another) is marked `drift`,
  while staying with one long video remains `leisure`.
* **Episodes** — the day is grouped into coherent stretches ("Coding on life-os
  for 52 min with 3 short detours to YouTube and WhatsApp"). Short hops inside
  an episode are collected as *detours* so scattered moments can be seen
  together instead of disappearing into totals.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from lifeos.models import ActivityCategory, ActivityEvent
from lifeos.services.activity import COMPUTER_SOURCES, event_interval, events_in_range
from lifeos.services.classification import clean_title
from lifeos.services.settings import get_settings
from lifeos.timeutil import utcnow

HOPPABLE = {"leisure", "drift"}
MAX_INTERRUPTION = timedelta(minutes=2)


def _item_key(e: ActivityEvent) -> str:
    """What the person was looking at: a video/page title, else the app."""
    t = clean_title(e.title)
    return f"{e.domain or e.app}|{t}" if t else (e.domain or e.app or "?")


# ---- drift detection -------------------------------------------------------------


@dataclass
class DriftRun:
    events: list[ActivityEvent]
    seconds: float
    distinct_items: int
    median_item_minutes: float
    shortform_share: float
    feed_share: float
    is_drift: bool
    reason: str


def find_hop_runs(events: list[ActivityEvent], cfg: dict[str, Any]) -> list[DriftRun]:
    """Group leisure/drift events (by rule category) into runs, tolerating brief
    interruptions, and judge each run."""
    evs = sorted(events, key=lambda e: e.start_time)
    runs: list[list[ActivityEvent]] = []
    cur: list[ActivityEvent] = []
    last_hop_end: datetime | None = None
    interruption = timedelta(0)
    for e in evs:
        hoppable = e.category_key in HOPPABLE and not e.category_override
        if hoppable:
            if cur and last_hop_end is not None and (e.start_time - last_hop_end) <= MAX_INTERRUPTION and interruption <= MAX_INTERRUPTION:
                cur.append(e)
            else:
                if cur:
                    runs.append(cur)
                cur = [e]
            last_hop_end = max(last_hop_end or e.end_time, e.end_time)
            interruption = timedelta(0)
        elif cur:
            interruption += e.end_time - e.start_time
            if interruption > MAX_INTERRUPTION:
                runs.append(cur)
                cur, last_hop_end = [], None
    if cur:
        runs.append(cur)
    return [judge_run(r, cfg) for r in runs]


def judge_run(run: list[ActivityEvent], cfg: dict[str, Any]) -> DriftRun:
    per_item: dict[str, float] = defaultdict(float)
    shortform = feed = total = 0.0
    for e in run:
        d = (e.end_time - e.start_time).total_seconds()
        total += d
        per_item[_item_key(e)] += d
        kind = (e.evidence or {}).get("url_kind")
        if kind == "shorts" or e.subcategory == "Short-form video":
            shortform += d
        if kind == "feed" or e.subcategory in {"Social feed", "Browsing video feed"}:
            feed += d
    distinct = len(per_item)
    median_min = statistics.median(per_item.values()) / 60 if per_item else 0.0
    sf_share = shortform / total if total else 0.0
    feed_share = feed / total if total else 0.0
    long_enough = total >= cfg["drift_min_run_minutes"] * 60
    hopping = distinct >= cfg["drift_min_distinct_items"] and median_min <= cfg["drift_max_median_item_minutes"]
    is_drift = long_enough and (hopping or sf_share >= 0.5 or feed_share >= 0.5)
    if not is_drift:
        reason = "steady" if long_enough else "short"
    elif hopping:
        reason = f"{distinct} different items, about {max(median_min, 0.1):.1f} min each"
    elif sf_share >= 0.5:
        reason = "mostly short-form video"
    else:
        reason = "mostly feeds"
    return DriftRun(run, total, distinct, median_min, sf_share, feed_share, is_drift, reason)


def apply_patterns(db: Session, lo: datetime, hi: datetime) -> int:
    """Recompute `pattern_category` for computer activity in [lo, hi)."""
    cfg = get_settings(db)["attention"]
    events = events_in_range(db, lo, hi, sources={"activitywatch", "activity_json"})
    changed = 0
    target: dict[int, str | None] = {e.id: None for e in events}
    by_device: dict[str | None, list[ActivityEvent]] = defaultdict(list)
    for e in events:
        if not (e.evidence or {}).get("explicit_category"):  # content-free devices judged themselves
            by_device[e.device_id].append(e)
    for dev_events in by_device.values():
        for run in find_hop_runs(dev_events, cfg):
            if run.is_drift:
                for e in run.events:
                    if e.category_key == "leisure":
                        target[e.id] = "drift"
    for e in events:
        if e.pattern_category != target[e.id]:
            e.pattern_category = target[e.id]
            changed += 1
    db.commit()
    return changed


def apply_patterns_since(db: Session, days: int) -> int:
    now = utcnow()
    return apply_patterns(db, now - timedelta(days=days), now + timedelta(minutes=1))


# ---- episodes ------------------------------------------------------------------------


@dataclass
class Run:
    category: str
    start: datetime
    end: datetime
    seconds: float
    events: list[ActivityEvent]


@dataclass
class Episode:
    start: datetime
    end: datetime
    category: str
    device_id: str | None = None
    kind: str = "mixed"  # focus|mixed|drift|leisure|recovery
    seconds: float = 0.0
    summary: str = ""
    subcategories: dict[str, float] = field(default_factory=dict)
    top_items: list[tuple[str, float]] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    detours: list[dict[str, Any]] = field(default_factory=list)
    detour_seconds: float = 0.0
    switches: int = 0
    distinct_items: int = 0
    event_ids: list[int] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list, repr=False)
    detour_runs: list[Run] = field(default_factory=list, repr=False)


def _runs(events: list[ActivityEvent], lo: datetime, hi: datetime, gap: timedelta) -> list[Run]:
    out: list[Run] = []
    for e in sorted(events, key=lambda e: e.start_time):
        iv = event_interval(e, lo, hi)
        if iv is None:
            continue
        cat = e.effective_category
        d = (iv[1] - iv[0]).total_seconds()
        if out and out[-1].category == cat and iv[0] - out[-1].end < gap:
            r = out[-1]
            r.end = max(r.end, iv[1])
            r.seconds += d
            r.events.append(e)
        else:
            out.append(Run(cat, iv[0], iv[1], d, [e]))
    return out


def _label(e: ActivityEvent) -> str:
    return e.domain or e.app or e.activity or "Unknown"


def build_episodes(events: list[ActivityEvent], lo: datetime, hi: datetime, *, break_gap: timedelta, detour_max: timedelta,
                   names: dict[str, str] | None = None, productive: set[str] | None = None, focus_switches_per_hour: float = 18) -> list[Episode]:
    names = names or {}
    productive = productive or set()
    comp = [e for e in events if e.source in COMPUTER_SOURCES and not e.excluded]
    runs = _runs(comp, lo, hi, break_gap)
    eps: list[Episode] = []
    for r in runs:
        ep = eps[-1] if eps else None
        contiguous = ep is not None and r.start - ep.end < break_gap
        if contiguous and r.category == ep.category:
            ep.runs.append(r)
            ep.end = max(ep.end, r.end)
        elif contiguous and r.seconds < detour_max.total_seconds():
            ep.detour_runs.append(r)
            ep.end = max(ep.end, r.end)
        else:
            new = Episode(start=r.start, end=r.end, category=r.category, runs=[r])
            # Trailing detours of the new category actually started this episode.
            if contiguous and ep is not None:
                while ep.detour_runs and ep.detour_runs[-1].category == r.category and ep.detour_runs[-1].end >= ep.runs[-1].end:
                    d = ep.detour_runs.pop()
                    new.runs.insert(0, d)
                    new.start = d.start
                ep.end = max([x.end for x in ep.runs + ep.detour_runs])
            eps.append(new)

    # Fold tiny episodes into a contiguous neighbour as detours.
    merged: list[Episode] = []
    for i, ep in enumerate(eps):
        dur = sum(r.seconds for r in ep.runs)
        if dur < detour_max.total_seconds():
            nxt = eps[i + 1] if i + 1 < len(eps) else None
            prev = merged[-1] if merged else None
            if prev and ep.start - prev.end < break_gap:
                prev.detour_runs += ep.runs + ep.detour_runs
                prev.end = max(prev.end, ep.end)
                continue
            if nxt and nxt.start - ep.end < break_gap:
                nxt.detour_runs = ep.runs + ep.detour_runs + nxt.detour_runs
                nxt.start = min(nxt.start, ep.start)
                continue
        merged.append(ep)

    for ep in merged:
        _finalise(ep, names, productive, focus_switches_per_hour)
    return merged


def _rebalance(ep: Episode) -> float:
    """Name an episode after what dominated it, not what happened first.
    Unclassified time counts half so it rarely names an episode."""
    every = ep.runs + ep.detour_runs
    weight: dict[str, float] = defaultdict(float)
    for r in every:
        weight[r.category] += r.seconds * (0.5 if r.category == "other" else 1.0)
    dominant = max(weight, key=weight.get)
    ep.category = dominant
    ep.runs = sorted((r for r in every if r.category == dominant), key=lambda r: r.start)
    ep.detour_runs = sorted((r for r in every if r.category != dominant), key=lambda r: r.start)
    total = sum(r.seconds for r in every)
    return sum(r.seconds for r in ep.runs) / total if total else 1.0


def _finalise(ep: Episode, names: dict[str, str], productive: set[str], focus_sph: float) -> None:
    share = _rebalance(ep)
    main = [e for r in ep.runs for e in r.events]
    det = [e for r in ep.detour_runs for e in r.events]
    ep.seconds = sum(r.seconds for r in ep.runs)
    ep.detour_seconds = sum(r.seconds for r in ep.detour_runs)
    ep.event_ids = [e.id for e in main + det]
    subs: Counter[str] = Counter()
    items: Counter[str] = Counter()
    projects: Counter[str] = Counter()
    distinct = set()
    for e in main:
        d = (e.end_time - e.start_time).total_seconds()
        subs[e.effective_subcategory or names.get(e.effective_category, e.effective_category)] += d
        items[_label(e)] += d
        distinct.add(_item_key(e))
        if (e.evidence or {}).get("project"):
            projects[e.evidence["project"]] += d
    ep.subcategories = dict(subs.most_common())
    ep.top_items = items.most_common(4)
    ep.projects = [p for p, _ in projects.most_common(3)]
    ep.distinct_items = len(distinct)
    seq = sorted(main + det, key=lambda e: e.start_time)
    ep.switches = sum(1 for a, b in zip(seq, seq[1:]) if (a.app, a.domain) != (b.app, b.domain))

    dgroups: dict[tuple[str, str], dict[str, Any]] = {}
    for r in ep.detour_runs:
        for e in r.events:
            key = (e.effective_category, _label(e))
            g = dgroups.setdefault(key, {"category": key[0], "label": key[1], "seconds": 0.0, "count": 0, "first_at": e.start_time})
            g["seconds"] += (e.end_time - e.start_time).total_seconds()
        for key in {(e.effective_category, _label(e)) for e in r.events}:
            dgroups[key]["count"] += 1
    ep.detours = sorted(dgroups.values(), key=lambda g: -g["seconds"])

    minutes = ep.seconds / 60
    hours = max((ep.end - ep.start).total_seconds() / 3600, 1 / 60)
    sph = ep.switches / hours
    cat = ep.category
    if share < 0.6 and cat not in {"drift"}:
        ep.kind = "mixed"
    elif cat == "drift":
        ep.kind = "drift"
    elif cat == "leisure":
        ep.kind = "leisure"
    elif cat == "recovery":
        ep.kind = "recovery"
    elif cat in productive and ep.detour_seconds <= 0.25 * (ep.seconds + ep.detour_seconds) and sph <= focus_sph:
        ep.kind = "focus"
    else:
        ep.kind = "mixed"

    top_sub = next(iter(ep.subcategories), names.get(cat, cat))
    where = ", ".join(i for i, _ in ep.top_items[:2])
    if ep.kind == "drift":
        ep.summary = f"Hopped through {ep.distinct_items} items on {where} ({minutes:.0f} min)"
    elif share < 0.6:
        mix: Counter[str] = Counter()
        for r in ep.runs + ep.detour_runs:
            for e in r.events:
                mix[_label(e)] += (e.end_time - e.start_time).total_seconds()
        total_min = (ep.seconds + ep.detour_seconds) / 60
        ep.summary = f"Switching between {', '.join(f'{k} {v / 60:.0f}m' for k, v in mix.most_common(3))} ({total_min:.0f} min)"
        return  # hops still feed the day's detour tally, just not this sentence
    elif ep.kind == "leisure":
        ep.summary = f"{top_sub} on {where} ({minutes:.0f} min)"
    else:
        proj = f" on {ep.projects[0]}" if ep.projects else ""
        ep.summary = f"{top_sub}{proj} — {where} ({minutes:.0f} min)"
    if ep.detours:
        n = sum(d["count"] for d in ep.detours)
        by_site: Counter[str] = Counter()
        for d in ep.detours:
            by_site[d["label"]] += d["seconds"]
        srcs = ", ".join(f"{k} {v / 60:.0f}m" for k, v in by_site.most_common(3))
        ep.summary += f" · {n} detour{'s' if n != 1 else ''} ({srcs})"


def detour_summary(episodes: list[Episode]) -> dict[str, Any]:
    by_label: dict[str, dict[str, Any]] = {}
    count = 0
    total = 0.0
    for ep in episodes:
        if ep.kind in {"drift", "leisure", "recovery"}:
            continue
        for d in ep.detours:
            count += d["count"]
            total += d["seconds"]
            g = by_label.setdefault(d["label"], {"label": d["label"], "category": d["category"], "seconds": 0.0, "count": 0})
            g["seconds"] += d["seconds"]
            g["count"] += d["count"]
    return {"count": count, "seconds": total, "sources": sorted(by_label.values(), key=lambda g: -g["seconds"])[:8]}


def episodes_for_range(db: Session, lo: datetime, hi: datetime) -> tuple[list[Episode], dict[str, Any]]:
    s = get_settings(db)
    cats = db.query(ActivityCategory).all()
    names = {c.key: c.name for c in cats}
    productive = {c.key for c in cats if c.is_productive}
    events = events_in_range(db, lo, hi, sources=COMPUTER_SOURCES)
    by_device: dict[str | None, list[ActivityEvent]] = defaultdict(list)
    for e in events:
        by_device[e.device_id].append(e)
    eps: list[Episode] = []
    for dev, dev_events in by_device.items():
        for ep in build_episodes(
            dev_events, lo, hi,
            break_gap=timedelta(minutes=s["recovery"]["break_gap_minutes"]),
            detour_max=timedelta(minutes=s["attention"]["detour_max_minutes"]),
            names=names, productive=productive,
            focus_switches_per_hour=s["recovery"]["deep_work_switches_per_hour"] * 1.5,
        ):
            ep.device_id = dev
            eps.append(ep)
    eps.sort(key=lambda e: e.start)
    return eps, detour_summary(eps)


def episode_out(ep: Episode) -> dict[str, Any]:
    return {
        "start": ep.start, "end": ep.end, "category": ep.category, "kind": ep.kind, "seconds": ep.seconds, "device_id": ep.device_id,
        "summary": ep.summary, "subcategories": ep.subcategories, "top_items": ep.top_items, "projects": ep.projects,
        "detours": ep.detours, "detour_seconds": ep.detour_seconds, "switches": ep.switches,
        "distinct_items": ep.distinct_items, "event_ids": ep.event_ids,
    }


def recent_drift(db: Session, now: datetime, window: timedelta = timedelta(minutes=20)) -> dict[str, Any] | None:
    """Drift in the last `window` if the person is still in it (for live nudges)."""
    events = events_in_range(db, now - window, now, sources={"activitywatch", "activity_json"})
    if not events:
        return None
    last = max(events, key=lambda e: e.end_time)
    if now - last.end_time > timedelta(minutes=3) or last.effective_category != "drift":
        return None
    drift = [e for e in events if e.effective_category == "drift" and not e.confirmed and not e.category_override]
    secs = sum((min(e.end_time, now) - max(e.start_time, now - window)).total_seconds() for e in drift)
    if not drift:
        return None
    labels = Counter(_label(e) for e in drift)
    return {
        "seconds": secs,
        "items": len({_item_key(e) for e in drift}),
        "sources": [l for l, _ in labels.most_common(2)],
        "event_ids": [e.id for e in drift],
    }
