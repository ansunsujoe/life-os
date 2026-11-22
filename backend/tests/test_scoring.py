from datetime import date, datetime, timedelta

from lifeos.models import Checkin, ClaudeSession, SessionStateChange, Task, TaskMilestone, WeeklyGoal
from lifeos.services.activity import NormalizedEvent, upsert_events
from lifeos.services.goals import GoalProgress, capped_ratio, compute_goal_progress
from lifeos.services.scoring import (
    Dimension,
    attention_response_times,
    combine,
    compute_score,
    goals_dimension,
    recovery_dimension,
    stretch_score,
)
from lifeos.services.settings import DEFAULT_SETTINGS, update_settings
from lifeos.timeutil import local_today, utcnow, week_start


def test_capped_ratio_never_rewards_overachievement():
    assert capped_ratio(10, 3) == 1.0
    assert capped_ratio(1, 4) == 0.25


def test_combine_renormalises_over_included_dimensions():
    dims = [
        Dimension("progress", "", 0.5, None, False, "", []),
        Dimension("maintenance", "", 0.2, 0.5, True, "", []),
        Dimension("recovery", "", 0.2, 1.0, True, "", []),
        Dimension("intentionality", "", 0.1, None, False, "", []),
    ]
    overall, eff = combine(dims)
    assert eff == {"maintenance": 0.5, "recovery": 0.5}
    assert overall == 0.75


def test_goals_dimension_averages_within_domain_first():
    ps = [
        GoalProgress(1, "software", "a", "manual", 1, 1, 1.0, "high"),
        GoalProgress(2, "software", "b", "manual", 1, 1, 1.0, "high"),
        GoalProgress(3, "software", "c", "manual", 1, 1, 1.0, "high"),
        GoalProgress(4, "music", "m", "manual", 2, 0, 0.0, "high"),
    ]
    d = goals_dimension("progress", ps, ["software", "music"], 0.5)
    assert d.score == 0.5  # three software goals don't drown out music


def test_rest_days_score_full_recovery():
    days = {date(2026, 3, d): [] for d in range(2, 9)}
    days[date(2026, 3, 2)] = [(datetime(2026, 3, 2, 15), datetime(2026, 3, 2, 16))]
    d = recovery_dimension(days, DEFAULT_SETTINGS["recovery"], 0.2, [], [], 0)
    assert d.score == 1.0


def test_long_unbroken_stretches_lower_recovery_but_logging_breaks_only_helps():
    s = datetime(2026, 3, 2, 12)
    days = {date(2026, 3, 2): [(s, s + timedelta(hours=5))]}
    base = recovery_dimension(days, DEFAULT_SETTINGS["recovery"], 0.2, [], [], 0).score
    with_breaks = recovery_dimension(days, DEFAULT_SETTINGS["recovery"], 0.2, [], [], 3).score
    assert base < 1.0 and with_breaks > base
    assert stretch_score(90) == 1.0 and stretch_score(400) == 0.4


def test_more_screen_time_never_raises_score(db):
    today = local_today("America/Chicago")
    day_start = datetime.combine(today, datetime.min.time()) + timedelta(hours=8)  # 02:00/03:00 local
    upsert_events(db, [NormalizedEvent("a", "activitywatch", day_start, day_start + timedelta(hours=1), device_id="personal-mac", app="Code")])
    low = compute_score(db, today)
    upsert_events(db, [NormalizedEvent("b", "activitywatch", day_start + timedelta(hours=1), day_start + timedelta(hours=7), device_id="personal-mac", app="Code")])
    high = compute_score(db, today)
    assert high["overall"] <= low["overall"]


def test_goal_measures_and_faith_exclusion(db):
    tz = "America/Chicago"
    today = local_today(tz)
    wk = week_start(today)
    g_faith = WeeklyGoal(week_start=wk, domain="faith", title="Scripture", measure="checkins", target=4)
    g_soft = WeeklyGoal(week_start=wk, domain="software", title="Ship", measure="milestones", target=2)
    db.add_all([g_faith, g_soft])
    t = Task(title="API", domain="software", status="in_progress")
    t.milestones.append(TaskMilestone(title="m1", done=True, completed_at=utcnow()))
    db.add(t)
    now = utcnow()
    # Two check-ins on the same day count once: practice rhythm, not volume.
    db.add_all([
        Checkin(domain="faith", kind="scripture", at=now, details={"local_day": today.isoformat()}),
        Checkin(domain="faith", kind="prayer", at=now, details={"local_day": today.isoformat()}),
    ])
    db.commit()
    assert compute_goal_progress(db, g_faith, tz, until=today).value == 1
    assert compute_goal_progress(db, g_soft, tz, until=today).ratio == 0.5

    with_faith = compute_score(db, today)
    maint = next(d for d in with_faith["dimensions"] if d["key"] == "maintenance")
    assert maint["included"] and maint["score"] == 25.0

    update_settings(db, {"include_faith_in_score": False})
    without = compute_score(db, today)
    maint = next(d for d in without["dimensions"] if d["key"] == "maintenance")
    assert not maint["included"]  # excluded, not penalised


def test_attention_response_times():
    t0 = datetime(2026, 3, 2, 12)
    ch = [
        SessionStateChange(session_id=1, to_state="ready", needs_attention=True, at=t0),
        SessionStateChange(session_id=1, to_state="generating", needs_attention=False, at=t0 + timedelta(minutes=4)),
        SessionStateChange(session_id=2, to_state="waiting", needs_attention=True, at=t0),
        SessionStateChange(session_id=2, to_state="generating", needs_attention=False, at=t0 + timedelta(minutes=30)),
    ]
    assert sorted(attention_response_times(ch)) == [4, 30]


def test_score_explains_itself(db):
    s = compute_score(db, local_today("America/Chicago"))
    for d in s["dimensions"]:
        assert d["note"]
    assert {d["key"] for d in s["dimensions"]} == {"progress", "maintenance", "recovery", "intentionality"}
    _ = ClaudeSession  # imported for model registration in some runners
