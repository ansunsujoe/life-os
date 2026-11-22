"""Projects, tasks, milestones, weekly goals, Claude sessions."""

from __future__ import annotations

import socket
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from lifeos import schemas
from lifeos.db import get_db
from lifeos.models import ClaudeSession, Project, SessionStateChange, Task, TaskMilestone, WeeklyGoal
from lifeos.serialize import row
from lifeos.services.goals import compute_goal_progress, copy_goals_forward, goals_for_week
from lifeos.services.sessions import apply_hook_event, create_session, session_view, set_state
from lifeos.services.settings import get_settings
from lifeos.seed import detect_local_device_id
from lifeos.timeutil import local_today, utcnow, week_start

router = APIRouter(prefix="/api", tags=["work"])


# ---- projects ----------------------------------------------------------------
@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    out = []
    for p in db.query(Project).order_by(Project.status, Project.name):
        tasks = db.query(Task).filter(Task.project_id == p.id)
        out.append({**row(p), "open_tasks": tasks.filter(Task.status.in_(["todo", "in_progress", "blocked"])).count(), "done_tasks": tasks.filter(Task.status == "done").count()})
    return out


@router.post("/projects")
def create_project(body: schemas.ProjectIn, db: Session = Depends(get_db)):
    p = Project(**body.model_dump())
    db.add(p)
    db.commit()
    return row(p)


@router.patch("/projects/{pid}")
def patch_project(pid: int, body: schemas.ProjectPatch, db: Session = Depends(get_db)):
    p = db.get(Project, pid) or _404()
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    return row(p)


@router.delete("/projects/{pid}")
def delete_project(pid: int, db: Session = Depends(get_db)):
    p = db.get(Project, pid) or _404()
    db.delete(p)
    db.commit()
    return {"deleted": pid}


# ---- tasks -------------------------------------------------------------------
def _task_out(t: Task) -> dict[str, Any]:
    ms = [row(m) for m in t.milestones]
    return {**row(t), "milestones": ms, "milestones_done": sum(1 for m in t.milestones if m.done)}


def _404() -> Any:
    raise HTTPException(404)


@router.get("/tasks")
def list_tasks(status: str | None = None, domain: str | None = None, project_id: int | None = None, include_done: bool = False, db: Session = Depends(get_db)):
    q = db.query(Task)
    if status:
        q = q.filter(Task.status == status)
    elif not include_done:
        q = q.filter(Task.status.in_(["todo", "in_progress", "blocked"]))
    if domain:
        q = q.filter(Task.domain == domain)
    if project_id:
        q = q.filter(Task.project_id == project_id)
    return [_task_out(t) for t in q.order_by(Task.priority.desc(), Task.due_date.is_(None), Task.due_date, Task.id)]


def _apply_status(t: Task, status: str) -> None:
    now = utcnow()
    if status == "in_progress" and not t.started_at:
        t.started_at = now
    if status == "done" and t.status != "done":
        t.completed_at = now
        t.last_progress_at = now
    if status != "done":
        t.completed_at = None
    t.status = status


@router.post("/tasks")
def create_task(body: schemas.TaskIn, db: Session = Depends(get_db)):
    data = body.model_dump()
    milestones = data.pop("milestones")
    status = data.pop("status")
    t = Task(**data)
    _apply_status(t, status)
    for i, m in enumerate(x for x in milestones if x.strip()):
        t.milestones.append(TaskMilestone(title=m.strip(), sort_order=i))
    db.add(t)
    db.commit()
    return _task_out(t)


@router.patch("/tasks/{tid}")
def patch_task(tid: int, body: schemas.TaskPatch, db: Session = Depends(get_db)):
    t = db.get(Task, tid) or _404()
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        _apply_status(t, data.pop("status"))
    for k, v in data.items():
        setattr(t, k, v)
    db.commit()
    return _task_out(t)


@router.post("/tasks/{tid}/attempt")
def record_attempt(tid: int, success: bool = False, db: Session = Depends(get_db)):
    """Track unsuccessful attempts so stagnation can be noticed — without blame."""
    t = db.get(Task, tid) or _404()
    if success:
        t.failed_attempts = 0
        t.last_progress_at = utcnow()
    else:
        t.failed_attempts += 1
    db.commit()
    return _task_out(t)


@router.delete("/tasks/{tid}")
def delete_task(tid: int, db: Session = Depends(get_db)):
    t = db.get(Task, tid) or _404()
    db.delete(t)
    db.commit()
    return {"deleted": tid}


@router.post("/tasks/{tid}/milestones")
def add_milestone(tid: int, body: schemas.MilestoneIn, db: Session = Depends(get_db)):
    t = db.get(Task, tid) or _404()
    t.milestones.append(TaskMilestone(title=body.title, sort_order=len(t.milestones)))
    db.commit()
    return _task_out(t)


@router.patch("/milestones/{mid}")
def patch_milestone(mid: int, body: schemas.MilestonePatch, db: Session = Depends(get_db)):
    m = db.get(TaskMilestone, mid) or _404()
    data = body.model_dump(exclude_unset=True)
    if "done" in data:
        m.done = data.pop("done")
        m.completed_at = utcnow() if m.done else None
        if m.done:
            m.task.last_progress_at = utcnow()
            m.task.failed_attempts = 0
            if m.task.status == "todo":
                _apply_status(m.task, "in_progress")
    for k, v in data.items():
        setattr(m, k, v)
    db.commit()
    return _task_out(m.task)


@router.delete("/milestones/{mid}")
def delete_milestone(mid: int, db: Session = Depends(get_db)):
    m = db.get(TaskMilestone, mid) or _404()
    task = m.task
    db.delete(m)
    db.commit()
    db.refresh(task)
    return _task_out(task)


# ---- weekly goals ------------------------------------------------------------
@router.get("/goals")
def list_goals(week: date | None = None, db: Session = Depends(get_db)):
    tz_name = get_settings(db)["timezone"]
    today = local_today(tz_name)
    wk = week_start(week or today)
    until = today if wk == week_start(today) else None
    goals = goals_for_week(db, wk)
    return {
        "week_start": wk,
        "goals": [{**row(g), "progress": compute_goal_progress(db, g, tz_name, until=until)} for g in goals],
        "previous_week_has_goals": bool(goals_for_week(db, wk - timedelta(days=7))),
    }


@router.post("/goals")
def create_goal(body: schemas.GoalIn, db: Session = Depends(get_db)):
    data = body.model_dump()
    data["week_start"] = week_start(data["week_start"] or local_today(get_settings(db)["timezone"]))
    g = WeeklyGoal(**data)
    db.add(g)
    db.commit()
    return row(g)


@router.patch("/goals/{gid}")
def patch_goal(gid: int, body: schemas.GoalPatch, db: Session = Depends(get_db)):
    g = db.get(WeeklyGoal, gid) or _404()
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(g, k, v)
    db.commit()
    return row(g)


@router.delete("/goals/{gid}")
def delete_goal(gid: int, db: Session = Depends(get_db)):
    g = db.get(WeeklyGoal, gid) or _404()
    db.delete(g)
    db.commit()
    return {"deleted": gid}


@router.post("/goals/copy-forward")
def goals_copy_forward(week: date | None = None, db: Session = Depends(get_db)):
    wk = week_start(week or local_today(get_settings(db)["timezone"]))
    return {"copied": copy_goals_forward(db, wk - timedelta(days=7), wk)}


# ---- Claude sessions ---------------------------------------------------------
def _session_out(s: ClaudeSession, settings: dict[str, Any]) -> dict[str, Any]:
    now = utcnow()
    return {**row(s), **session_view(s, now, timedelta(minutes=settings["sessions"]["idle_after_minutes"]))}


@router.get("/sessions")
def list_sessions(include_completed: bool = False, db: Session = Depends(get_db)):
    settings = get_settings(db)
    q = db.query(ClaudeSession)
    if not include_completed:
        cutoff = utcnow() - timedelta(hours=12)
        q = q.filter((ClaudeSession.state != "completed") | (ClaudeSession.state_changed_at >= cutoff))
    items = [_session_out(s, settings) for s in q.order_by(ClaudeSession.needs_attention.desc(), ClaudeSession.priority.desc(), ClaudeSession.last_interaction_at.desc())]
    counts: dict[str, int] = {}
    for s in items:
        counts[s["state"]] = counts.get(s["state"], 0) + 1
    return {"sessions": items, "counts": counts, "needs_attention": sum(1 for s in items if s["needs_attention"])}


@router.post("/sessions")
def new_session(body: schemas.SessionIn, db: Session = Depends(get_db)):
    data = body.model_dump()
    data["device_id"] = data["device_id"] or detect_local_device_id()
    s = create_session(db, **data, source="manual")
    return _session_out(s, get_settings(db))


@router.patch("/sessions/{sid}")
def patch_session(sid: int, body: schemas.SessionPatch, db: Session = Depends(get_db)):
    s = db.get(ClaudeSession, sid) or _404()
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    return _session_out(s, get_settings(db))


@router.post("/sessions/{sid}/state")
def change_state(sid: int, body: schemas.SessionStateIn, db: Session = Depends(get_db)):
    s = db.get(ClaudeSession, sid) or _404()
    set_state(db, s, body.state, needs_attention=body.needs_attention, source="manual")
    db.commit()
    return _session_out(s, get_settings(db))


@router.delete("/sessions/{sid}")
def delete_session(sid: int, db: Session = Depends(get_db)):
    s = db.get(ClaudeSession, sid) or _404()
    db.query(SessionStateChange).filter_by(session_id=sid).delete()
    db.delete(s)
    db.commit()
    return {"deleted": sid}


@router.get("/sessions/{sid}/history")
def session_history(sid: int, db: Session = Depends(get_db)):
    return [row(c) for c in db.query(SessionStateChange).filter_by(session_id=sid).order_by(SessionStateChange.at)]


@router.post("/sessions/hook")
def claude_code_hook(payload: dict[str, Any], db: Session = Depends(get_db)):
    """Receives Claude Code hook payloads from hooks/lifeos_hook.py (localhost only)."""
    settings = get_settings(db)
    device = payload.pop("lifeos_device_id", None) or detect_local_device_id() or socket.gethostname()
    try:
        s = apply_hook_event(db, payload, device, settings["privacy"]["claude_hook_capture_prompt"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "session_id": s.id if s else None, "state": s.state if s else None}
