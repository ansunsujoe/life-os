"""Populate a *separate* database with realistic demo data to explore the UI.

    LIFEOS_HOME=~/LifeOS-demo uv run python -m lifeos.demo

Refuses to run against a database that already has activity, so it can never
pollute real data.
"""

from __future__ import annotations

import random
import sys
from datetime import date, datetime, time, timedelta

from lifeos.config import config
from lifeos.db import SessionLocal
from lifeos.main import init_app_db
from lifeos.models import ActivityEvent, Checkin, HealthMetric, Project, Task, TaskMilestone, TradingNote, WeeklyGoal
from lifeos.seed import detect_local_device_id
from lifeos.services.activity import NormalizedEvent, upsert_events
from lifeos.services.sessions import create_session, set_state
from lifeos.services.settings import get_settings
from lifeos.timeutil import get_zone, local_day_bounds, local_today, to_utc_naive, utcnow, week_start

BLOCKS = [
    # (app, title, domain, minutes)
    ("Code", "orchestrator.py — life-os", None, 50),
    ("Terminal", "claude — life-os", None, 25),
    ("Google Chrome", "Pull request #12", "github.com", 15),
    ("Slack", "team", None, 10),
    ("Logic Pro", "Night Theme.logicx", None, 45),
    ("Google Chrome", "AAPL chart", "tradingview.com", 20),
    ("Google Chrome", "Rust ownership tutorial", "frontendmasters.com", 30),
    ("Finder", "Downloads", None, 5),
    ("Google Chrome", "News", "news.ycombinator.com", 12),
]


def main() -> None:
    init_app_db()
    db = SessionLocal()
    if db.query(ActivityEvent).count() > 0:
        print(f"Refusing: {config.db_path} already has activity. Point LIFEOS_HOME at an empty folder.")
        sys.exit(1)
    tz_name = get_settings(db)["timezone"]
    tz = get_zone(tz_name)
    dev = detect_local_device_id()
    today = local_today(tz_name)
    now = utcnow()
    rng = random.Random(7)

    events: list[NormalizedEvent] = []
    for back in range(13, -1, -1):
        d = today - timedelta(days=back)
        if d.weekday() == 6 and back:  # Sundays off
            continue
        cursor = to_utc_naive(datetime.combine(d, time(8, 30), tzinfo=tz))
        end_of_day = to_utc_naive(datetime.combine(d, time(rng.choice([17, 18, 19]), 0), tzinfo=tz))
        i = 0
        while cursor < min(end_of_day, now):
            app, title, domain, mins = BLOCKS[rng.randrange(len(BLOCKS))] if rng.random() > 0.35 else BLOCKS[i % 3]
            dur = timedelta(minutes=max(3, int(mins * rng.uniform(0.5, 1.4))))
            end = min(cursor + dur, now)
            events.append(NormalizedEvent(f"demo:{d}:{i}", "activitywatch", cursor, end, device_id=dev, app=app, title=title, domain=domain))
            cursor = end + timedelta(minutes=rng.choice([0, 0, 1, 2, 8, 15]))
            i += 1
    upsert_events(db, events)

    lifeos = Project(name="LifeOS", domain="software", description="Personal productivity system")
    album = Project(name="Night Theme", domain="music", description="Orchestral cue")
    db.add_all([lifeos, album])
    db.flush()
    t1 = Task(title="Build Today dashboard", domain="software", project_id=lifeos.id, priority=3, mental_demand="high", status="in_progress",
              next_action="Wire timeline to /api/today", estimate_minutes=120, started_at=now - timedelta(days=2), last_progress_at=now - timedelta(hours=5))
    for j, m in enumerate(["Timeline component", "Category totals", "Correction menu"]):
        t1.milestones.append(TaskMilestone(title=m, sort_order=j, done=j == 0, completed_at=now - timedelta(hours=5) if j == 0 else None))
    t2 = Task(title="Reply to PR review comments", domain="software", project_id=lifeos.id, priority=2, mental_demand="low", estimate_minutes=15)
    t3 = Task(title="Arrange bridge section", domain="music", project_id=album.id, priority=2, mental_demand="medium", estimate_minutes=60,
              next_action="Sketch string voicing for bars 33–48")
    t4 = Task(title="Read chapter 4 of Rust book", domain="learning", priority=1, mental_demand="medium", estimate_minutes=45)
    db.add_all([t1, t2, t3, t4])

    wk = week_start(today)
    db.add_all([
        WeeklyGoal(week_start=wk, domain="software", title="Ship LifeOS Phase 2", measure="milestones", target=3),
        WeeklyGoal(week_start=wk, domain="music", title="Complete an arrangement milestone", measure="milestones", target=1),
        WeeklyGoal(week_start=wk, domain="learning", title="Rust practice", measure="checkins", target=3),
        WeeklyGoal(week_start=wk, domain="health", title="Exercise", measure="workouts", target=3),
        WeeklyGoal(week_start=wk, domain="faith", title="Scripture & prayer", measure="checkins", target=5),
        WeeklyGoal(week_start=wk, domain="trading", title="Journal every trading day", measure="manual", target=3, manual_progress=1),
    ])
    for back in range(0, 6, 2):
        d = today - timedelta(days=back)
        at = to_utc_naive(datetime.combine(d, time(7, 0), tzinfo=tz))
        if at < now:
            db.add(Checkin(domain="faith", kind="scripture_prayer", title="Morning reading", at=at, details={"local_day": d.isoformat()}))
            db.add(HealthMetric(source_key=f"demo:workout:{d}", metric="workout", day=d, start_time=at + timedelta(hours=10),
                                end_time=at + timedelta(hours=10, minutes=40), value=40, unit="min", details={"type": "Running"}))
        db.add(HealthMetric(source_key=f"demo:sleep:{d}", metric="sleep_minutes", day=d, start_time=local_day_bounds(d, tz_name)[0],
                            end_time=local_day_bounds(d, tz_name)[1], value=rng.choice([390, 420, 450]), unit="min"))
    db.add(Checkin(domain="learning", kind="checkpoint", title="Rust borrow checker", note="Shared vs mutable refs", at=now - timedelta(days=1),
                   details={"local_day": (today - timedelta(days=1)).isoformat()}))
    db.add(TradingNote(day=today - timedelta(days=1), instrument="AAPL", followed_plan=True, risk_sized=True, reason_recorded=True, rules_followed=True,
                       entry_reason="Breakout above range with volume"))
    db.commit()

    a = create_session(db, project="life-os", objective="Build Today dashboard", task_id=t1.id, state="generating", client="claude_code", device_id=dev)
    b = create_session(db, project="life-os", objective="Write scoring tests", state="generating", client="claude_code", device_id=dev)
    set_state(db, b, "ready", at=now - timedelta(minutes=7))
    c = create_session(db, project="blog", objective="Draft post about LifeOS", state="waiting", client="browser", device_id=dev, needs_attention=False)
    c.expected_next_action = "Decide on outline"
    db.commit()
    _ = (a, date)
    print(f"Demo data written to {config.db_path}")


if __name__ == "__main__":
    main()
