"""Transparent, configurable scoring (spec §4).

- Measures meaningful progress and sustainable balance, not raw hours.
- Every dimension exposes its components and evidence.
- Dimensions without relevant data/goals are excluded and weights renormalised
  (a domain that isn't relevant this week never drags the score down).
- Credit is capped: overworking one domain cannot inflate the score.
- Rest never lowers a score: days off score perfectly on recovery.
- Orchestration is computed separately and is *not* part of the life score.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from lifeos.models import Checkin, ClaudeSession, HealthMetric, SessionStateChange, Task, TaskMilestone
from lifeos.services.activity import COMPUTER_SOURCES, event_interval, events_in_range
from lifeos.services.goals import GoalProgress, compute_goal_progress, goals_for_week, milestones_in_range
from lifeos.services.intervals import Interval, continuous_stretches, intersect, total_seconds, union
from lifeos.services.recovery import switches_per_hour
from lifeos.services.settings import get_settings
from lifeos.timeutil import local_day_bounds, local_range_bounds, utcnow, week_start

DIMENSION_NAMES = {
    "progress": "Meaningful progress",
    "maintenance": "Physical & spiritual maintenance",
    "recovery": "Recovery & life balance",
    "intentionality": "Intentionality",
}


@dataclass
class Component:
    key: str
    name: str
    score: float | None  # 0..1
    detail: str
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Dimension:
    key: str
    name: str
    weight: float
    score: float | None  # 0..1, None = excluded
    included: bool
    note: str
    components: list[Component]


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def combine(dims: list[Dimension]) -> tuple[float | None, dict[str, float]]:
    """Weighted mean over included dimensions; weights renormalised."""
    inc = [d for d in dims if d.included and d.score is not None and d.weight > 0]
    tot = sum(d.weight for d in inc)
    if not inc or tot <= 0:
        return None, {}
    eff = {d.key: d.weight / tot for d in inc}
    return sum(d.score * eff[d.key] for d in inc), eff


def goals_dimension(key: str, progresses: list[GoalProgress], domains: list[str], weight: float) -> Dimension:
    """Average goals within a domain first, then across domains, so many goals in
    one domain don't outweigh others."""
    by_domain: dict[str, list[GoalProgress]] = defaultdict(list)
    for p in progresses:
        if p.domain in domains:
            by_domain[p.domain].append(p)
    comps = []
    for dom, ps in sorted(by_domain.items()):
        comps.append(
            Component(
                key=dom,
                name=dom.capitalize(),
                score=mean([p.ratio for p in ps]),
                detail="; ".join(f"{p.title}: {p.value:g}/{p.target:g}" for p in ps),
                evidence=[{"goal_id": p.goal_id, "title": p.title, "value": p.value, "target": p.target, "ratio": p.ratio, "confidence": p.confidence, "evidence": p.evidence[:20]} for p in ps],
            )
        )
    score = mean([c.score for c in comps if c.score is not None])
    if score is None:
        return Dimension(key, DIMENSION_NAMES[key], weight, None, False, "No weekly goals in these domains — excluded, not penalised.", comps)
    return Dimension(key, DIMENSION_NAMES[key], weight, score, True, "Average of capped weekly-goal progress (100% max per goal).", comps)


def stretch_score(longest_minutes: float) -> float:
    """1.0 up to 2h continuous; linearly down to 0.4 at 5h+."""
    if longest_minutes <= 120:
        return 1.0
    return max(0.4, 1.0 - 0.6 * (longest_minutes - 120) / 180)


def screen_score(hours: float, soft_limit: float) -> float:
    if hours <= soft_limit:
        return 1.0
    return max(0.3, 1.0 - 0.7 * (hours - soft_limit) / 4)


def recovery_dimension(
    day_intervals: dict[date, list[Interval]],
    thresholds: dict[str, Any],
    weight: float,
    sleep_minutes: list[float],
    recovery_goals: list[GoalProgress],
    recovery_checkins: int,
) -> Dimension:
    gap = timedelta(minutes=thresholds["break_gap_minutes"])
    long_after = thresholds["short_break_after_minutes"]
    s_scores, b_scores, sc_scores = [], [], []
    ev_days = []
    for d, ivs in sorted(day_intervals.items()):
        stretches = continuous_stretches(ivs, gap)
        longest = max(((e - s).total_seconds() / 60 for s, e in stretches), default=0.0)
        active_min = total_seconds(ivs) / 60
        over = sum(max(0.0, (e - s).total_seconds() / 60 - long_after) for s, e in stretches)
        s_scores.append(stretch_score(longest))
        b_scores.append(1.0 - min(1.0, over / active_min) if active_min > 0 else 1.0)
        sc_scores.append(screen_score(active_min / 60, thresholds["daily_screen_soft_limit_hours"]))
        ev_days.append({"day": d.isoformat(), "active_minutes": round(active_min), "longest_stretch_minutes": round(longest), "stretches": len(stretches)})
    comps = [
        Component("stretches", "Sustainable stretches", mean(s_scores), "Longest continuous screen stretch per day (days off score 100%).", ev_days),
        Component("breaks", "Breaks taken", mean(b_scores), f"Share of screen time not spent beyond {long_after} min without a break."),
        Component("screen", "Screen-time balance", mean(sc_scores), f"Days within the {thresholds['daily_screen_soft_limit_hours']}h soft limit."),
    ]
    if sleep_minutes:
        avg = sum(sleep_minutes) / len(sleep_minutes)
        comps.append(Component("sleep", "Sleep (Apple Health)", min(1.0, avg / 420), f"Average {avg / 60:.1f}h asleep (context, not diagnosis)."))
    if recovery_goals:
        comps.append(Component("goals", "Recovery goals", mean([g.ratio for g in recovery_goals]), "; ".join(f"{g.title}: {g.value:g}/{g.target:g}" for g in recovery_goals)))
    has_data = any(d["active_minutes"] > 0 for d in ev_days) or sleep_minutes or recovery_goals or recovery_checkins
    if not has_data:
        return Dimension("recovery", DIMENSION_NAMES["recovery"], weight, None, False, "No activity or recovery data yet.", comps)
    score = mean([c.score for c in comps if c.score is not None])
    # Logged recovery (breaks, offline time) can only raise the score.
    bonus = min(0.1, 0.02 * recovery_checkins)
    if score is not None:
        score = min(1.0, score + bonus)
    note = "Breaks and rest never lower this score." + (f" +{bonus * 100:.0f} for {recovery_checkins} logged recovery check-ins." if bonus else "")
    return Dimension("recovery", DIMENSION_NAMES["recovery"], weight, score, score is not None, note, comps)


def intentionality_dimension(events, lo, hi, goal_domains: set[str], weight: float) -> Dimension:
    by_cat: dict[str, list[Interval]] = defaultdict(list)
    for e in events:
        if e.source not in COMPUTER_SOURCES:
            continue
        iv = event_interval(e, lo, hi)
        if iv:
            by_cat[e.effective_category].append(iv)
    total = total_seconds([iv for ivs in by_cat.values() for iv in ivs])
    if total < 600:
        return Dimension("intentionality", DIMENSION_NAMES["intentionality"], weight, None, False, "Not enough tracked activity yet.", [])
    other = total_seconds(by_cat.get("other", []))
    drift = total_seconds(by_cat.get("drift", []))
    unpurposeful = other + drift
    classified_share = 1 - unpurposeful / total
    detail = f"{classified_share * 100:.0f}% of tracked time had a clear purpose"
    if drift >= 60:
        detail += f"; {drift / 60:.0f} min was drift/scrolling (chosen leisure doesn't count against you)"
    comps = [Component("classified", "Time with a clear purpose", classified_share, detail + ".")]
    other = unpurposeful
    if goal_domains:
        aligned = total_seconds([iv for c, ivs in by_cat.items() if c in goal_domains or c in {"recovery", "leisure"} for iv in ivs])
        classified = total - other
        if classified > 0:
            comps.append(Component("aligned", "Aligned with weekly priorities", aligned / classified, f"Share of purposeful time in domains you set goals for: {', '.join(sorted(goal_domains))}."))
    return Dimension("intentionality", DIMENSION_NAMES["intentionality"], weight, mean([c.score for c in comps]), True, "Deliberate time, not more time.", comps)


def compute_score(db: Session, end_day: date) -> dict[str, Any]:
    s = get_settings(db)
    tz_name, weights, domains = s["timezone"], s["score_weights"], s["domains"]
    wk = week_start(end_day)
    first = end_day - timedelta(days=6)
    lo, hi = local_range_bounds(first, end_day, tz_name)
    hi = min(hi, utcnow())

    progresses = [compute_goal_progress(db, g, tz_name, until=end_day) for g in goals_for_week(db, wk)]
    maint_domains = [d for d in domains["maintenance"] if d != "faith" or s["include_faith_in_score"]]

    progress = goals_dimension("progress", progresses, domains["progress"], weights["progress"])
    wlo, whi = local_range_bounds(wk, end_day, tz_name)
    ms = [m for m in milestones_in_range(db, wlo, whi) if m["domain"] in domains["progress"]]
    progress.components.append(Component("milestones", "Milestones this week", None, f"{len(ms)} verified milestone(s) — shown as evidence.", ms[:30]))

    maintenance = goals_dimension("maintenance", progresses, maint_domains, weights["maintenance"])

    events = events_in_range(db, lo, hi)
    day_ivs: dict[date, list[Interval]] = {}
    for i in range(7):
        d = first + timedelta(days=i)
        dlo, dhi = local_day_bounds(d, tz_name)
        day_ivs[d] = union([iv for e in events if e.source in COMPUTER_SOURCES and (iv := event_interval(e, dlo, min(dhi, hi)))])
    sleep = [h.value for h in db.query(HealthMetric).filter(HealthMetric.metric == "sleep_minutes", HealthMetric.day >= first, HealthMetric.day <= end_day)]
    rec_checkins = db.query(Checkin).filter(Checkin.domain == "recovery", Checkin.at >= lo, Checkin.at < hi).count()
    recovery = recovery_dimension(day_ivs, s["recovery"], weights["recovery"], sleep, [p for p in progresses if p.domain in domains["recovery"]], rec_checkins)

    goal_domains = {p.domain for p in progresses if p.domain in domains["progress"] + maint_domains}
    intentionality = intentionality_dimension(events, lo, hi, goal_domains, weights["intentionality"])

    dims = [progress, maintenance, recovery, intentionality]
    overall, eff = combine(dims)
    return {
        "end_day": end_day.isoformat(),
        "window": {"from": first.isoformat(), "to": end_day.isoformat(), "goal_week": wk.isoformat()},
        "overall": round(overall * 100, 1) if overall is not None else None,
        "effective_weights": eff,
        "dimensions": [_dim_out(d) for d in dims],
        "goals": [asdict(p) for p in progresses],
    }


def _dim_out(d: Dimension) -> dict[str, Any]:
    out = asdict(d)
    out["score"] = round(d.score * 100, 1) if d.score is not None else None
    for c in out["components"]:
        c["score"] = round(c["score"] * 100, 1) if c["score"] is not None else None
    return out


# ---- Orchestration (separate from productivity) -----------------------------


def attention_response_times(changes: list[SessionStateChange]) -> list[float]:
    """Minutes from a session needing attention until the user responded."""
    by_session: dict[int, list[SessionStateChange]] = defaultdict(list)
    for c in sorted(changes, key=lambda c: c.at):
        by_session[c.session_id].append(c)
    out = []
    for cs in by_session.values():
        flagged_at = None
        for c in cs:
            if c.needs_attention and flagged_at is None:
                flagged_at = c.at
            elif not c.needs_attention and flagged_at is not None:
                out.append((c.at - flagged_at).total_seconds() / 60)
                flagged_at = None
    return out


def generating_intervals(changes: list[SessionStateChange], lo: datetime, hi: datetime) -> list[Interval]:
    by_session: dict[int, list[SessionStateChange]] = defaultdict(list)
    for c in sorted(changes, key=lambda c: c.at):
        by_session[c.session_id].append(c)
    ivs = []
    for cs in by_session.values():
        start = None
        for c in cs:
            if c.to_state == "generating" and start is None:
                start = c.at
            elif c.to_state != "generating" and start is not None:
                ivs.append((start, c.at))
                start = None
        if start is not None:
            ivs.append((start, min(hi, start + timedelta(hours=2))))
    return [iv for iv in ((max(s, lo), min(e, hi)) for s, e in ivs) if iv[0] < iv[1]]


def compute_orchestration(db: Session, end_day: date) -> dict[str, Any]:
    s = get_settings(db)
    tz_name, w, rec = s["timezone"], s["orchestration_weights"], s["recovery"]
    first = end_day - timedelta(days=6)
    lo, hi = local_range_bounds(first, end_day, tz_name)
    hi = min(hi, utcnow())
    changes = db.query(SessionStateChange).filter(SessionStateChange.at >= lo - timedelta(hours=2), SessionStateChange.at < hi).all()
    sessions = db.query(ClaudeSession).filter(ClaudeSession.last_interaction_at >= lo).all()
    comps: dict[str, Component] = {}

    # P — parallel progress: distinct tasks/projects with verified progress vs. parallel session load.
    ms = db.query(TaskMilestone).filter(TaskMilestone.done.is_(True), TaskMilestone.completed_at >= lo, TaskMilestone.completed_at < hi).all()
    done_tasks = db.query(Task).filter(Task.status == "done", Task.completed_at >= lo, Task.completed_at < hi).all()
    progressed = {m.task_id for m in ms} | {t.id for t in done_tasks}
    session_projects = {x.project or f"session-{x.id}" for x in sessions}
    if session_projects:
        comps["P"] = Component("P", "Parallel progress", min(1.0, len(progressed) / len(session_projects)), f"{len(progressed)} task(s) progressed across {len(session_projects)} session project(s). More sessions without progress lowers this.")

    # W — waiting-time utilisation: while Claude generated, were you doing something else useful or resting?
    gen = union(generating_intervals(changes, lo, hi))
    if total_seconds(gen) >= 300:
        evs = events_in_range(db, lo, hi, sources=COMPUTER_SOURCES)
        other_ivs = [iv for e in evs if e.effective_category in {"other"} and (iv := event_interval(e, lo, hi))]
        wasted = total_seconds(intersect(gen, other_ivs))
        g = total_seconds(gen)
        comps["W"] = Component("W", "Waiting-time use", 1 - wasted / g, f"{g / 60:.0f} min of generation time; {wasted / 60:.0f} min overlapped unclassified activity. Breaks count as good use.")

    # C — effective context switching.
    evs = events_in_range(db, lo, hi, sources={"activitywatch"})
    if evs:
        sph = switches_per_hour(evs, lo, hi)
        healthy, high = rec["deep_work_switches_per_hour"], rec["high_switches_per_hour"]
        c = 1.0 if sph <= healthy else max(0.0, 1 - (sph - healthy) / max(1, high - healthy))
        comps["C"] = Component("C", "Context switching", c, f"{sph:.0f} app switches per active hour (healthy ≤ {healthy}).")

    # T — task completion.
    touched = db.query(Task).filter(Task.status == "in_progress", Task.updated_at >= lo).count()
    if done_tasks or ms or touched:
        done = len(done_tasks) + len(ms)
        comps["T"] = Component("T", "Task completion", done / (done + touched) if done + touched else None, f"{len(done_tasks)} task(s) and {len(ms)} milestone(s) completed; {touched} still in progress.")

    # A — attention management.
    rts = attention_response_times(changes)
    if rts:
        stale = s["sessions"]["attention_stale_minutes"]
        comps["A"] = Component("A", "Attention management", sum(1 for r in rts if r <= stale) / len(rts), f"{len(rts)} attention request(s); median response {sorted(rts)[len(rts) // 2]:.0f} min (target ≤ {stale}).")

    avail = {k: c for k, c in comps.items() if c.score is not None}
    tot = sum(w[k] for k in avail)
    m = sum(w[k] * c.score for k, c in avail.items()) / tot if tot else None
    return {
        "exploratory": True,
        "formula": "M = 0.30P + 0.25W + 0.20C + 0.15T + 0.10A (weights configurable; missing components excluded)",
        "score": round(m * 100, 1) if m is not None else None,
        "weights": w,
        "components": [{**asdict(c), "score": round(c.score * 100, 1) if c.score is not None else None} for c in comps.values()],
    }
