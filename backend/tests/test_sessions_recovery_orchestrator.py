from datetime import date, datetime, timedelta

from lifeos.models import ClaudeSession, RecommendationFeedback, Task
from lifeos.services.orchestrator import build_candidates, recommend
from lifeos.services.recovery import RecoveryAssessment, assess
from lifeos.services.sessions import apply_hook_event, create_session, set_state
from lifeos.services.settings import DEFAULT_SETTINGS
from lifeos.timeutil import utcnow

TH = DEFAULT_SETTINGS["recovery"]
NOW = datetime(2026, 3, 2, 20, 0)


# ---- sessions ------------------------------------------------------------------


def test_manual_state_changes_set_attention_defaults(db):
    s = create_session(db, project="api", objective="refactor", state="generating")
    assert not s.needs_attention
    set_state(db, s, "ready")
    assert s.needs_attention and s.attention_since is not None
    set_state(db, s, "generating")
    assert not s.needs_attention and s.attention_since is None
    set_state(db, s, "paused", needs_attention=True)
    assert s.needs_attention
    set_state(db, s, "completed", needs_attention=True)
    assert not s.needs_attention  # completed sessions never need attention


def test_claude_code_hook_lifecycle(db):
    base = {"session_id": "abc", "cwd": "/Users/me/projects/life-os"}
    s = apply_hook_event(db, {**base, "hook_event_name": "SessionStart"}, "personal-mac", False)
    assert (s.project, s.state, s.source) == ("life-os", "ready", "claude_hook")
    s = apply_hook_event(db, {**base, "hook_event_name": "UserPromptSubmit", "prompt": "secret plan"}, "personal-mac", False)
    assert s.state == "generating" and s.objective == ""  # prompt not captured unless enabled
    s = apply_hook_event(db, {**base, "hook_event_name": "Notification", "message": "Claude needs your permission to use Bash"}, None, False)
    assert s.state == "waiting" and s.needs_attention
    s = apply_hook_event(db, {**base, "hook_event_name": "PostToolUse"}, None, False)
    assert s.state == "generating"
    s = apply_hook_event(db, {**base, "hook_event_name": "Stop"}, None, False)
    assert s.state == "ready" and s.needs_attention
    s = apply_hook_event(db, {**base, "hook_event_name": "SessionEnd"}, None, False)
    assert s.state == "completed" and not s.needs_attention
    assert db.query(ClaudeSession).count() == 1


def test_hook_can_capture_first_prompt_line_when_enabled(db):
    s = apply_hook_event(db, {"session_id": "x", "hook_event_name": "UserPromptSubmit", "prompt": "Fix the login bug\nmore"}, None, True)
    assert s.objective == "Fix the login bug"


# ---- recovery ------------------------------------------------------------------


def _active(minutes: int) -> list:
    return [(NOW - timedelta(minutes=minutes), NOW)]


def _assess(minutes, **kw):
    args = dict(now=NOW, active=_active(minutes), recent_events=[], thresholds=TH, energy=None, screen_today_seconds=minutes * 60, local_hour=14)
    args.update(kw)
    return assess(**args)


def test_no_break_suggested_for_short_work():
    assert _assess(30).level == "none"


def test_single_signal_gives_only_gentle_nudge():
    r = _assess(95)  # one signal: >90 min
    assert r.level == "micro"


def test_deep_work_is_protected_until_long_stretch():
    r = _assess(100, energy=4, screen_today_seconds=10 * 3600)  # 2 signals but focused work
    assert r.level == "micro" and r.deep_work_protected


def test_low_energy_plus_long_stretch_suggests_real_break():
    r = _assess(160, energy=2)
    assert r.level in {"long", "deep"} and len(r.reasons) >= 2


def test_late_long_day_suggests_stopping():
    r = _assess(40, local_hour=22, screen_today_seconds=8 * 3600)
    assert r.level == "deep"


def test_currently_away_counts_as_break():
    r = assess(now=NOW, active=[(NOW - timedelta(hours=3), NOW - timedelta(minutes=20))], recent_events=[], thresholds=TH,
               energy=1, screen_today_seconds=3 * 3600, local_hour=14)
    assert r.level == "none" and r.signals["current_stretch_minutes"] == 0


# ---- orchestrator --------------------------------------------------------------


def _none_recovery():
    return RecoveryAssessment("none", None, None, [], {})


def _cands(**kw):
    args = dict(now=NOW, today=date(2026, 3, 2), local_hour=14, sessions=[], tasks=[], stalled=[], recovery=_none_recovery(),
                energy=None, goal_progress=[], weekday=0, trading_today=False, trading_note_today=False, review_done=True,
                current_category=None, settings=DEFAULT_SETTINGS)
    args.update(kw)
    return sorted(build_candidates(**args), key=lambda c: -c.score)


def test_ready_session_outranks_ordinary_tasks():
    s = ClaudeSession(id=1, project="api", state="ready", needs_attention=True, priority=2, attention_since=NOW - timedelta(minutes=10),
                      state_changed_at=NOW, last_interaction_at=NOW, expected_next_action="")
    t = Task(id=5, title="Write docs", priority=3, status="todo", mental_demand="medium")
    c = _cands(sessions=[s], tasks=[t])
    assert c[0].kind == "session" and "ready for review" in c[0].reason


def test_parallel_task_suggested_while_generating():
    s = ClaudeSession(id=1, project="api", state="generating", needs_attention=False, priority=2, state_changed_at=NOW, last_interaction_at=NOW, expected_next_action="")
    short = Task(id=7, title="Reply to PR comment", priority=2, status="todo", mental_demand="low", estimate_minutes=10)
    long = Task(id=8, title="Design schema", priority=2, status="todo", mental_demand="high", estimate_minutes=120)
    c = _cands(sessions=[s], tasks=[short, long])
    par = [x for x in c if x.kind == "parallel_task"]
    assert par and par[0].target == {"type": "task", "id": 7}


def test_low_energy_prefers_low_demand_tasks():
    hard = Task(id=1, title="Hard", priority=2, status="todo", mental_demand="high")
    easy = Task(id=2, title="Easy", priority=2, status="todo", mental_demand="low")
    c = [x for x in _cands(tasks=[hard, easy], energy=2) if x.kind == "task"]
    assert c[0].target["id"] == 2


def test_break_recommendation_includes_reason():
    rec = RecoveryAssessment("long", "Long break (20–40 min)", "Go offline", ["You've been at the screen for 160 minutes without a break."], {})
    c = _cands(recovery=rec)
    assert c[0].kind == "break" and "160 minutes" in c[0].reason


def test_dismissed_recommendations_are_hidden(db):
    db.add(Task(title="Only task", priority=2, status="todo"))
    db.commit()
    first = recommend(db)["top"]
    assert first and first["kind"] == "task"
    db.add(RecommendationFeedback(rec_key=first["key"], kind=first["kind"], title=first["title"], action="dismissed", at=utcnow()))
    db.commit()
    assert recommend(db)["top"] is None
