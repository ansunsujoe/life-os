"""Adaptive break recommendations.

Principles (spec §8): several signals together, never a single one for a strong
conclusion; protect focused deep work; watch data is context, never diagnosis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from lifeos.models import ActivityEvent, Checkin, DailyReview, HealthMetric, Task
from lifeos.services.activity import COMPUTER_SOURCES, event_interval, events_in_range
from lifeos.services.intervals import Interval, continuous_stretches, total_seconds, union
from lifeos.services.settings import get_settings
from lifeos.timeutil import local_day_bounds, local_today, to_local, utcnow

LEVELS = ["none", "micro", "short", "long", "deep"]
SUGGESTIONS = {
    "micro": ("Microbreak (2–5 min)", "Stand up, stretch, rest your eyes on something far away."),
    "short": ("Short break (5–15 min)", "Take a short walk, get water, step away from the screen."),
    "long": ("Long break (20–40 min)", "Go offline for a while — a walk outside, a meal, time with people."),
    "deep": ("Deep recovery (1h+)", "Consider an intentional stop for the day. The work will keep."),
}


@dataclass
class RecoveryAssessment:
    level: str
    title: str | None
    suggestion: str | None
    reasons: list[str]
    signals: dict[str, Any]
    deep_work_protected: bool = False
    points: int = 0
    context: list[str] = field(default_factory=list)


def switches_per_hour(events: list[ActivityEvent], lo: datetime, hi: datetime) -> float:
    """App/category switches per active hour (consecutive distinct app runs)."""
    evs = sorted((e for e in events if e.source == "activitywatch"), key=lambda e: e.start_time)
    prev = None
    switches = 0
    ivs: list[Interval] = []
    for e in evs:
        iv = event_interval(e, lo, hi)
        if iv is None:
            continue
        ivs.append(iv)
        key = (e.app, e.domain)
        if prev is not None and key != prev:
            switches += 1
        prev = key
    hours = total_seconds(ivs) / 3600
    return switches / hours if hours >= 0.25 else 0.0


def assess(
    *,
    now: datetime,
    active: list[Interval],
    recent_events: list[ActivityEvent],
    thresholds: dict[str, Any],
    energy: int | None,
    screen_today_seconds: float,
    local_hour: int,
    struggling_task: str | None = None,
    steps_today: float | None = None,
    break_style: str = "adaptive",
) -> RecoveryAssessment:
    """Pure function: combine signals into a break recommendation."""
    gap = timedelta(minutes=thresholds["break_gap_minutes"])
    stretches = continuous_stretches(active, gap)
    current = 0.0
    since_break = None
    if stretches and now - stretches[-1][1] < gap:
        current = (now - stretches[-1][0]).total_seconds() / 60
        since_break = current
    elif stretches:
        since_break = 0.0  # currently away from the computer: that *is* a break
    sph = switches_per_hour(recent_events, now - timedelta(hours=1), now)
    screen_h = screen_today_seconds / 3600

    signals = {
        "current_stretch_minutes": round(current, 1),
        "minutes_since_break": round(since_break, 1) if since_break is not None else None,
        "switches_per_hour": round(sph, 1),
        "screen_today_hours": round(screen_h, 2),
        "energy": energy,
        "steps_today": steps_today,
    }
    reasons: list[str] = []
    context: list[str] = []
    points = 0
    t = thresholds

    if current >= t["long_break_after_minutes"]:
        points += 2
        reasons.append(f"You've been at the screen for {int(current)} minutes without a break.")
    elif current >= t["short_break_after_minutes"]:
        points += 1
        reasons.append(f"About {int(current)} minutes of continuous screen time.")
    elif current >= t["micro_break_after_minutes"] and sph >= t["deep_work_switches_per_hour"]:
        points += 1
        reasons.append(f"{int(current)} minutes of fairly fragmented work.")

    if sph >= t["high_switches_per_hour"] and current >= 20:
        points += 1
        reasons.append(f"Lots of switching ({int(sph)} app changes in the last hour).")
    if energy is not None and energy <= 2 and current >= 20:
        points += 1
        reasons.append("You reported low energy today.")
    if screen_h >= t["daily_screen_soft_limit_hours"]:
        points += 1
        reasons.append(f"{screen_h:.1f} hours of screen time today.")
    if struggling_task and current >= 30:
        points += 1
        reasons.append(f"'{struggling_task}' has had several unsuccessful attempts — a reset may help.")
    if steps_today is not None and steps_today < 2000 and local_hour >= 15 and current >= t["micro_break_after_minutes"]:
        points += 1
        reasons.append("Little movement recorded today (context from your watch, not a diagnosis).")

    if break_style == "excessive_only":
        points = points if current >= t["long_break_after_minutes"] else 0

    if points == 0:
        level = "none"
    elif points == 1:
        level = "micro" if current >= t["micro_break_after_minutes"] else "none"
    elif points == 2:
        level = "short"
    elif points == 3:
        level = "long"
    else:
        level = "deep"

    late = local_hour >= t["end_of_day_hour"] and screen_h >= 6 and current > 0
    if late:
        level = "deep"
        reasons.append("It's late and you've had a long screen day.")

    # Deep-work protection: focused (low-switching) work isn't interrupted for
    # moderate stretches unless energy is low or it's late.
    protected = False
    if (
        level in {"short", "long"}
        and sph < t["deep_work_switches_per_hour"]
        and current < t["long_break_after_minutes"]
        and not (energy is not None and energy <= 2)
        and not late
    ):
        level, protected = "micro", True
        context.append("You seem to be in focused work, so this is only a gentle nudge.")

    title, suggestion = SUGGESTIONS.get(level, (None, None))
    return RecoveryAssessment(level, title, suggestion, reasons if level != "none" else [], signals, protected, points, context)


def today_energy(db: Session, today) -> int | None:
    r = db.get(DailyReview, today)
    if r and r.energy:
        return r.energy
    c = db.query(Checkin).filter(Checkin.kind == "energy").order_by(Checkin.at.desc()).first()
    if c and c.value is not None and c.details.get("local_day") == today.isoformat():
        return int(c.value)
    return None


def current_assessment(db: Session, now: datetime | None = None) -> RecoveryAssessment:
    now = now or utcnow()
    s = get_settings(db)
    tz_name = s["timezone"]
    today = local_today(tz_name)
    lo, hi = local_day_bounds(today, tz_name)
    events = events_in_range(db, lo - timedelta(hours=6), now, sources=COMPUTER_SOURCES)
    active = union([iv for e in events if (iv := event_interval(e, lo - timedelta(hours=6), now))])
    today_ivs = [iv for e in events if (iv := event_interval(e, lo, now))]
    struggling = (
        db.query(Task).filter(Task.status == "in_progress", Task.failed_attempts >= 3).order_by(Task.updated_at.desc()).first()
    )
    steps = db.query(HealthMetric).filter(HealthMetric.metric == "steps", HealthMetric.day == today).first()
    return assess(
        now=now,
        active=active,
        recent_events=[e for e in events if e.end_time >= now - timedelta(hours=1)],
        thresholds=s["recovery"],
        energy=today_energy(db, today),
        screen_today_seconds=total_seconds(today_ivs),
        local_hour=to_local(now, tz_name).hour,
        struggling_task=struggling.title if struggling else None,
        steps_today=steps.value if steps else None,
        break_style=s["preferences"]["break_style"],
    )
