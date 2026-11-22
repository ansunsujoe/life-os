"""Claude session manager: manual registration (Level 2) and Claude Code hooks (Level 3)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from lifeos.models import ClaudeSession, SessionStateChange
from lifeos.timeutil import utcnow

STATES = ("generating", "ready", "blocked", "waiting", "paused", "completed")
ACTIVE_STATES = {"generating", "ready", "blocked", "waiting", "paused"}
# States that, by themselves, mean the ball is in the user's court.
ATTENTION_STATES = {"ready", "blocked", "waiting"}


def set_state(
    db: Session,
    s: ClaudeSession,
    state: str | None = None,
    *,
    needs_attention: bool | None = None,
    source: str = "manual",
    at: datetime | None = None,
) -> ClaudeSession:
    at = at or utcnow()
    if state is not None and state not in STATES:
        raise ValueError(f"Unknown session state: {state}")
    prev_state, prev_att = s.state, s.needs_attention
    if state is not None:
        s.state = state
    if needs_attention is None and state is not None and state != prev_state:
        # Sensible default: finishing generation or getting stuck needs the user.
        needs_attention = state in ATTENTION_STATES
    if s.state == "completed":
        needs_attention = False
    if needs_attention is not None:
        s.needs_attention = needs_attention
    if s.needs_attention and not prev_att:
        s.attention_since = at
    elif not s.needs_attention:
        s.attention_since = None
    s.last_interaction_at = at
    if s.state != prev_state or s.needs_attention != prev_att:
        if s.state != prev_state:
            s.state_changed_at = at
        db.add(SessionStateChange(session_id=s.id, from_state=prev_state, to_state=s.state, needs_attention=s.needs_attention, at=at, source=source))
    return s


def create_session(db: Session, **fields: Any) -> ClaudeSession:
    now = utcnow()
    state = fields.pop("state", "ready")
    needs_attention = fields.pop("needs_attention", None)
    s = ClaudeSession(started_at=now, last_interaction_at=now, state_changed_at=now, state=state, **fields)
    if needs_attention is None:
        needs_attention = False
    s.needs_attention = needs_attention
    s.attention_since = now if needs_attention else None
    db.add(s)
    db.flush()
    db.add(SessionStateChange(session_id=s.id, from_state=None, to_state=state, needs_attention=s.needs_attention, at=now, source=fields.get("source", "manual")))
    db.commit()
    return s


# ---- Claude Code hooks ------------------------------------------------------
# Hook events (https://docs.claude.com/en/docs/claude-code/hooks):
#   SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Notification,
#   Stop, SubagentStop, PreCompact, SessionEnd.
# Payload (stdin JSON) includes session_id, transcript_path, cwd, hook_event_name.

HOOK_TRANSITIONS: dict[str, tuple[str | None, bool | None]] = {
    "SessionStart": ("ready", False),
    "UserPromptSubmit": ("generating", False),
    "PreToolUse": ("generating", None),
    "PostToolUse": ("generating", None),
    "Stop": ("ready", True),  # output ready for review
    "SessionEnd": ("completed", False),
}


def apply_hook_event(db: Session, payload: dict[str, Any], device_id: str | None, capture_prompt: bool) -> ClaudeSession | None:
    event = payload.get("hook_event_name") or payload.get("event")
    ext_id = payload.get("session_id")
    if not event or not ext_id:
        raise ValueError("hook payload requires hook_event_name and session_id")
    s = db.query(ClaudeSession).filter_by(external_id=ext_id).one_or_none()
    cwd = payload.get("cwd")
    if s is None:
        if event == "SessionEnd":
            return None
        project = Path(cwd).name if cwd else ""
        s = create_session(
            db, external_id=ext_id, project=project, objective="", client="claude_code",
            device_id=device_id, cwd=cwd, source="claude_hook", state="ready",
        )
    if event == "UserPromptSubmit" and capture_prompt and not s.objective:
        prompt = (payload.get("prompt") or "").strip().splitlines()
        if prompt:
            s.objective = prompt[0][:140]
    if event == "Notification":
        msg = (payload.get("message") or "").lower()
        ntype = (payload.get("notification_type") or "").lower()
        if "permission" in msg or "permission" in ntype:
            set_state(db, s, "waiting", needs_attention=True, source="claude_hook")
            s.expected_next_action = "Approve or deny a permission request"
        else:
            # Idle reminder: keep state, just flag attention.
            set_state(db, s, None, needs_attention=True, source="claude_hook")
    elif event in HOOK_TRANSITIONS:
        state, att = HOOK_TRANSITIONS[event]
        if event in {"PreToolUse", "PostToolUse"} and s.state == "generating":
            s.last_interaction_at = utcnow()
        else:
            set_state(db, s, state, needs_attention=att, source="claude_hook")
            if event == "Stop":
                s.expected_next_action = "Review Claude's output"
            elif event == "UserPromptSubmit":
                s.expected_next_action = ""
    else:
        s.last_interaction_at = utcnow()
    db.commit()
    return s


def session_view(s: ClaudeSession, now: datetime, idle_after: timedelta) -> dict[str, Any]:
    idle_for = now - s.last_interaction_at
    return {
        "is_idle": s.state in ACTIVE_STATES and s.state != "generating" and idle_for >= idle_after,
        "idle_minutes": round(idle_for.total_seconds() / 60, 1),
        "attention_minutes": round((now - s.attention_since).total_seconds() / 60, 1) if s.attention_since else None,
        "in_state_minutes": round((now - s.state_changed_at).total_seconds() / 60, 1),
    }
