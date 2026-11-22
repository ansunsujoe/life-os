"""Weekly goal progress, computed from evidence the user can inspect."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from lifeos.models import ActivityEvent, Checkin, HealthMetric, Task, TaskMilestone, WeeklyGoal
from lifeos.services.activity import category_summary, events_in_range
from lifeos.timeutil import local_range_bounds

MEASURES = ("manual", "milestones", "tasks_completed", "checkins", "workouts", "activity_minutes")


@dataclass
class GoalProgress:
    goal_id: int
    domain: str
    title: str
    measure: str
    target: float
    value: float
    ratio: float  # capped at 1.0 — overachievement earns no extra credit
    confidence: str
    evidence: list[dict[str, Any]] = field(default_factory=list)


def capped_ratio(value: float, target: float) -> float:
    if target <= 0:
        return 1.0 if value > 0 else 0.0
    return max(0.0, min(1.0, value / target))


def _range(start_day: date, end_day: date, tz_name: str) -> tuple[datetime, datetime]:
    return local_range_bounds(start_day, end_day, tz_name)


def milestones_in_range(db: Session, lo: datetime, hi: datetime, domain: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    q = db.query(TaskMilestone, Task).join(Task).filter(TaskMilestone.done.is_(True), TaskMilestone.completed_at >= lo, TaskMilestone.completed_at < hi)
    if domain:
        q = q.filter(Task.domain == domain)
    for m, t in q:
        out.append({"type": "task_milestone", "id": m.id, "title": m.title, "task": t.title, "domain": t.domain, "at": m.completed_at})
    cq = db.query(Checkin).filter(Checkin.kind == "milestone", Checkin.at >= lo, Checkin.at < hi)
    if domain:
        cq = cq.filter(Checkin.domain == domain)
    for c in cq:
        out.append({"type": "checkin_milestone", "id": c.id, "title": c.title or c.details.get("milestone", "Milestone"), "domain": c.domain, "at": c.at})
    return out


def compute_goal_progress(db: Session, goal: WeeklyGoal, tz_name: str, until: date | None = None) -> GoalProgress:
    first = goal.week_start
    last = min(first + timedelta(days=6), until) if until else first + timedelta(days=6)
    lo, hi = _range(first, last, tz_name)
    evidence: list[dict[str, Any]] = []
    value = 0.0
    confidence = "high"
    m = goal.measure
    if m == "manual":
        value = goal.manual_progress
        evidence.append({"type": "manual", "title": f"Manually recorded progress: {value:g}"})
    elif m == "milestones":
        ev = milestones_in_range(db, lo, hi, goal.domain)
        value, evidence = float(len(ev)), ev
    elif m == "tasks_completed":
        tasks = db.query(Task).filter(Task.domain == goal.domain, Task.status == "done", Task.completed_at >= lo, Task.completed_at < hi).all()
        value = float(len(tasks))
        evidence = [{"type": "task", "id": t.id, "title": t.title, "at": t.completed_at} for t in tasks]
    elif m == "checkins":
        q = db.query(Checkin).filter(Checkin.domain == goal.domain, Checkin.at >= lo, Checkin.at < hi)
        if goal.checkin_kind:
            q = q.filter(Checkin.kind == goal.checkin_kind)
        rows = q.all()
        # Count distinct days: a realistic practice goal, not a volume contest.
        days = {r.details.get("local_day") or r.at.date().isoformat() for r in rows}
        value = float(len(days))
        evidence = [{"type": "checkin", "id": r.id, "kind": r.kind, "title": r.title or r.kind, "at": r.at} for r in rows]
    elif m == "workouts":
        hw = db.query(HealthMetric).filter(HealthMetric.metric == "workout", HealthMetric.start_time >= lo, HealthMetric.start_time < hi).all()
        mw = db.query(Checkin).filter(Checkin.domain == "health", Checkin.kind == "workout", Checkin.at >= lo, Checkin.at < hi).all()
        value = float(len(hw) + len(mw))
        evidence = [{"type": "apple_health_workout", "id": h.id, "title": h.details.get("type", "Workout"), "at": h.start_time, "minutes": round(h.value)} for h in hw]
        evidence += [{"type": "manual_workout", "id": c.id, "title": c.title or "Workout", "at": c.at} for c in mw]
    elif m == "activity_minutes":
        events = events_in_range(db, lo, hi)
        summ = category_summary([e for e in events if e.effective_category == goal.domain], lo, hi)
        cat = summ["categories"].get(goal.domain, {"seconds": 0, "by_confidence": {}})
        value = round(cat["seconds"] / 60, 1)
        bc = cat.get("by_confidence", {})
        confidence = "high" if bc.get("high", 0) >= cat["seconds"] * 0.5 else "medium" if bc.get("medium", 0) + bc.get("high", 0) > 0 else "low"
        evidence.append({"type": "activity_minutes", "title": f"{value:g} min of {goal.domain} activity", "by_confidence": {k: round(v / 60) for k, v in bc.items()}})
    return GoalProgress(goal.id, goal.domain, goal.title, m, goal.target, value, capped_ratio(value, goal.target), confidence, evidence)


def goals_for_week(db: Session, week_start: date) -> list[WeeklyGoal]:
    return db.query(WeeklyGoal).filter(WeeklyGoal.week_start == week_start).order_by(WeeklyGoal.domain, WeeklyGoal.id).all()


def copy_goals_forward(db: Session, from_week: date, to_week: date) -> int:
    existing = {(g.domain, g.title) for g in goals_for_week(db, to_week)}
    n = 0
    for g in goals_for_week(db, from_week):
        if (g.domain, g.title) in existing:
            continue
        db.add(WeeklyGoal(week_start=to_week, domain=g.domain, title=g.title, measure=g.measure, target=g.target, checkin_kind=g.checkin_kind, notes=g.notes))
        n += 1
    db.commit()
    return n


def stalled_tasks(db: Session, now: datetime, stall_days: int) -> list[Task]:
    cutoff = now - timedelta(days=stall_days)
    out = []
    for t in db.query(Task).filter(Task.status == "in_progress").all():
        last = t.last_progress_at or t.started_at or t.created_at
        if last < cutoff or t.failed_attempts >= 3:
            out.append(t)
    return out


def activity_event_count(db: Session) -> int:
    return db.query(ActivityEvent).count()
