"""Next-action orchestrator: ranks candidate actions with explicit rules.

It only *recommends*. It never switches apps, edits projects, or trades.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from lifeos.models import ClaudeSession, DailyReview, RecommendationFeedback, Task, TradingEvent, TradingNote
from lifeos.services.activity import category_summary, events_in_range
from lifeos.services.goals import compute_goal_progress, goals_for_week, stalled_tasks
from lifeos.services.patterns import episodes_for_range, recent_drift
from lifeos.services.recovery import RecoveryAssessment, current_assessment, today_energy
from lifeos.services.sessions import ACTIVE_STATES
from lifeos.services.settings import get_settings
from lifeos.timeutil import local_day_bounds, local_today, to_local, utcnow, week_start

BREAK_SCORES = {"micro": 50, "short": 72, "long": 86, "deep": 95}


@dataclass
class Candidate:
    key: str
    kind: str
    title: str
    reason: str
    score: float
    target: dict[str, Any] | None = None
    details: list[str] = field(default_factory=list)
    event_ids: list[int] = field(default_factory=list)


def _task_score(t: Task, today: date, energy: int | None) -> tuple[float, list[str]]:
    why: list[str] = []
    score = 30 + 8 * t.priority
    if t.priority >= 3:
        why.append("high priority")
    if t.status == "in_progress":
        score += 8
        why.append("already in progress")
    if t.due_date:
        days = (t.due_date - today).days
        if days < 0:
            score += 20
            why.append("past its due date")
        elif days <= 2:
            score += 15
            why.append(f"due {'today' if days == 0 else 'soon'}")
    if energy is not None:
        if energy <= 2 and t.mental_demand == "high":
            score -= 15
        elif energy <= 2 and t.mental_demand == "low":
            score += 8
            why.append("low mental demand suits your energy")
        elif energy >= 4 and t.mental_demand == "high":
            score += 5
            why.append("good energy for demanding work")
    return score, why


def build_candidates(
    *,
    now: datetime,
    today: date,
    local_hour: int,
    sessions: list[ClaudeSession],
    tasks: list[Task],
    stalled: list[Task],
    recovery: RecoveryAssessment,
    energy: int | None,
    goal_progress: list[Any],
    weekday: int,
    trading_today: bool,
    trading_note_today: bool,
    review_done: bool,
    current_category: str | None,
    settings: dict[str, Any],
    drift: dict[str, Any] | None = None,
    resume_hint: str | None = None,
) -> list[Candidate]:
    out: list[Candidate] = []

    if drift and drift["seconds"] >= settings["attention"]["nudge_after_drift_minutes"] * 60:
        mins = int(drift["seconds"] // 60)
        where = " and ".join(drift["sources"]) or "feeds"
        reason = f"About {mins} min of quick hopping on {where} ({drift['items']} items). If it's a break, enjoy it — no judgement."
        if resume_hint:
            reason += f" If not, you were last on: {resume_hint}."
        out.append(Candidate(f"drift:{today.isoformat()}", "drift", "Still choosing this, or drifting?", reason, 78,
                             None, [], drift["event_ids"]))
    idle_after = timedelta(minutes=settings["sessions"]["idle_after_minutes"])
    generating = [s for s in sessions if s.state == "generating"]

    for s in sessions:
        label = s.project or s.objective or f"session #{s.id}"
        if s.needs_attention and s.state in ACTIVE_STATES:
            waited = (now - (s.attention_since or s.state_changed_at)).total_seconds() / 60
            score = 80 + 4 * s.priority + min(10, waited / 3)
            if s.state == "waiting":
                score += 5
                title, reason = f"Respond to {label}", f"This Claude session is waiting on you{' (permission request)' if 'permission' in s.expected_next_action.lower() else ''}."
            elif s.state == "blocked":
                title, reason = f"Unblock {label}", "This Claude session is blocked and needs your input."
            else:
                title, reason = f"Review output from {label}", "This Claude session is ready for review."
            if waited >= 5:
                reason += f" It has been waiting about {int(waited)} min."
            out.append(Candidate(f"session:{s.id}:{s.state}", "session", title, reason, score, {"type": "session", "id": s.id},
                                 [s.objective] if s.objective else []))
        elif s.state in {"blocked", "waiting", "paused"} and now - s.last_interaction_at >= idle_after * 4:
            out.append(Candidate(f"stale:{s.id}", "session_cleanup", f"Close or revisit {label}",
                                 f"This session has been {s.state} for a long time; closing it keeps your board honest.", 25, {"type": "session", "id": s.id}))

    if recovery.level != "none":
        score = BREAK_SCORES[recovery.level]
        reason = recovery.reasons[0] if recovery.reasons else "A break would help."
        if generating and recovery.level in {"micro", "short"}:
            score += 6
            reason += " Claude is generating, so it's a natural moment."
        kind = "stop" if recovery.level == "deep" else "break"
        out.append(Candidate(f"break:{recovery.level}:{today.isoformat()}", kind, recovery.title or "Take a break", reason, score,
                             None, recovery.reasons[1:] + recovery.context + ([recovery.suggestion] if recovery.suggestion else [])))

    session_task_ids = {s.task_id for s in generating if s.task_id}
    blocked_ids = {t.id for t in tasks if t.status in {"blocked"}}
    open_tasks = [t for t in tasks if t.status in {"todo", "in_progress"} and t.depends_on_id not in blocked_ids]
    if generating and not any(c.kind == "session" for c in out):
        short = [t for t in open_tasks if t.id not in session_task_ids and (t.estimate_minutes or 999) <= 30 and t.mental_demand != "high"]
        short.sort(key=lambda t: -_task_score(t, today, energy)[0])
        label = generating[0].project or "a session"
        if short:
            t = short[0]
            out.append(Candidate(f"parallel:{t.id}", "parallel_task", f"While {label} generates: {t.title}",
                                 "A short, independent task fits the time while Claude works.", 62, {"type": "task", "id": t.id},
                                 [f"Next action: {t.next_action}"] if t.next_action else []))
        else:
            out.append(Candidate(f"parallel:none:{today.isoformat()}", "parallel_task", f"While {label} generates: plan the next prompt or log a note",
                                 "Claude is generating. Use the wait for something light rather than watching output.", 40))

    stalled_ids = {t.id for t in stalled}
    for t in stalled:
        out.append(Candidate(f"stalled:{t.id}", "stalled", f"Try a smaller milestone on '{t.title}'",
                             "Your current task appears stalled; a smaller next step, a different approach, or asking Claude to explain the failure may help.",
                             55 + 3 * t.priority, {"type": "task", "id": t.id}))

    scored = []
    for t in open_tasks:
        if t.id in stalled_ids:
            continue
        sc, why = _task_score(t, today, energy)
        scored.append((sc, t, why))
    scored.sort(key=lambda x: -x[0])
    for sc, t, why in scored[:4]:
        verb = "Continue" if t.status == "in_progress" else "Start"
        reason = ("This task is " + ", ".join(why) + ".") if why else "Next item by priority."
        out.append(Candidate(f"task:{t.id}", "task", f"{verb}: {t.title}", reason, sc, {"type": "task", "id": t.id},
                             [f"Next action: {t.next_action}"] if t.next_action else []))

    for gp in goal_progress:
        if gp.ratio >= 1:
            continue
        if (gp.ratio == 0 and weekday >= 2) or (gp.ratio < 0.5 and weekday >= 3):
            score = 42 + 2 * weekday
            reason = "You haven't made progress on this weekly goal yet." if gp.ratio == 0 else "This weekly goal has room to grow this week."
            if gp.domain in {"music", "learning", "health"} and current_category == "software":
                score += 8
                reason += " It would also be a sensible change of context."
            out.append(Candidate(f"goal:{gp.goal_id}", "goal", f"Make progress on '{gp.title}'", reason, score, {"type": "goal", "id": gp.goal_id}))

    if trading_today and not trading_note_today:
        out.append(Candidate(f"trading_note:{today.isoformat()}", "trading_note", "Record a quick trading note",
                             "You traded or researched markets today; a 1-minute process note keeps the focus on discipline, not P&L.", 46))

    if local_hour >= 19 and not review_done:
        out.append(Candidate(f"review:{today.isoformat()}", "review", "Do the 60-second daily review",
                             "It fills gaps the tracker can't see. Skip anything that doesn't apply.", 36))
    return out


def _resume_hint(db: Session, lo: datetime, now: datetime, sessions: list[ClaudeSession], tasks: list[Task]) -> str | None:
    """Where the person left off: the last productive episode today, else a task."""
    eps, _ = episodes_for_range(db, max(lo, now - timedelta(hours=4)), now)
    for ep in reversed(eps):
        if ep.kind in {"focus", "mixed"} and ep.category not in {"other", "drift", "leisure", "recovery"}:
            sub = next(iter(ep.subcategories), ep.category)
            return f"{sub}{' on ' + ep.projects[0] if ep.projects else ''}"
    ready = [s for s in sessions if s.needs_attention]
    if ready:
        return f"Claude session '{ready[0].project or ready[0].objective}' (ready for review)"
    prog = [t for t in tasks if t.status == "in_progress"]
    return prog[0].title if prog else None


def recommend(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    s = get_settings(db)
    tz_name = s["timezone"]
    today = local_today(tz_name)
    local_now = to_local(now, tz_name)
    lo, hi = local_day_bounds(today, tz_name)

    sessions = db.query(ClaudeSession).filter(ClaudeSession.state != "completed").all()
    tasks = db.query(Task).filter(Task.status.in_(["todo", "in_progress", "blocked"])).all()
    goals = goals_for_week(db, week_start(today))
    gps = [compute_goal_progress(db, g, tz_name, until=today) for g in goals]
    recovery = current_assessment(db, now)
    recent = events_in_range(db, now - timedelta(minutes=30), now)
    cur_cat = None
    if recent:
        summ = category_summary(recent, now - timedelta(minutes=30), now)["categories"]
        cur_cat = max(summ.items(), key=lambda kv: kv[1]["seconds"])[0] if summ else None
    trading_today = db.query(TradingEvent).filter(TradingEvent.activity_date == today).count() > 0
    if not trading_today:
        tsumm = category_summary(events_in_range(db, lo, hi), lo, hi)["categories"].get("trading")
        trading_today = bool(tsumm and tsumm["seconds"] >= 15 * 60)

    cands = build_candidates(
        now=now, today=today, local_hour=local_now.hour, sessions=sessions, tasks=tasks,
        stalled=stalled_tasks(db, now, s["recovery"]["stall_days"]), recovery=recovery,
        energy=today_energy(db, today), goal_progress=gps, weekday=today.weekday(),
        trading_today=trading_today,
        trading_note_today=db.query(TradingNote).filter(TradingNote.day == today).count() > 0,
        review_done=db.get(DailyReview, today) is not None, current_category=cur_cat, settings=s,
        drift=recent_drift(db, now), resume_hint=_resume_hint(db, lo, now, sessions, tasks),
    )

    # Respect feedback: dismissed today or snoozed.
    fb = db.query(RecommendationFeedback).filter(RecommendationFeedback.at >= lo).all()
    hidden = set()
    for f in fb:
        if f.action == "dismissed" or (f.action == "snoozed" and f.snooze_until and f.snooze_until > now):
            hidden.add(f.rec_key)
        if f.action == "accepted" and now - f.at < timedelta(minutes=20):
            hidden.add(f.rec_key)
    visible = sorted((c for c in cands if c.key not in hidden), key=lambda c: -c.score)
    return {
        "generated_at": now,
        "top": asdict(visible[0]) if visible else None,
        "alternatives": [asdict(c) for c in visible[1:5]],
        "recovery": asdict(recovery),
        "hidden_count": len(cands) - len(visible),
    }
