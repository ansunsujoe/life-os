"""Request bodies (responses are plain dicts serialised by UTCJSONResponse)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from lifeos.timeutil import to_utc_naive

Confidence = Literal["high", "medium", "low"]
Demand = Literal["low", "medium", "high"]
SessionState = Literal["generating", "ready", "blocked", "waiting", "paused", "completed"]
TaskStatus = Literal["todo", "in_progress", "blocked", "done", "dropped"]
Measure = Literal["manual", "milestones", "tasks_completed", "checkins", "workouts", "activity_minutes"]


class _UTC(BaseModel):
    @field_validator("*", mode="after")
    @classmethod
    def _utc(cls, v: Any) -> Any:
        return to_utc_naive(v) if isinstance(v, datetime) else v


# ---- activity ----------------------------------------------------------------
class EventPatch(BaseModel):
    ids: list[int]
    category: str | None = None
    clear_override: bool = False
    excluded: bool | None = None
    confirmed: bool | None = None


class IngestBody(BaseModel):
    device_id: str
    events: list[dict[str, Any]]


class CategoryIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    name: str
    color: str = "gray"
    description: str = ""
    is_productive: bool = True


class CategoryPatch(BaseModel):
    name: str | None = None
    color: str | None = None
    description: str | None = None
    is_productive: bool | None = None
    active: bool | None = None
    sort_order: int | None = None


class RuleIn(BaseModel):
    name: str = ""
    field: Literal["app", "title", "domain", "any"]
    match_type: Literal["contains", "equals", "regex"] = "contains"
    pattern: str = Field(min_length=1)
    category_key: str
    confidence: Confidence = "medium"
    priority: int = 5
    activity_label: str | None = None
    enabled: bool = True


class RulePatch(BaseModel):
    name: str | None = None
    field: Literal["app", "title", "domain", "any"] | None = None
    match_type: Literal["contains", "equals", "regex"] | None = None
    pattern: str | None = None
    category_key: str | None = None
    confidence: Confidence | None = None
    priority: int | None = None
    activity_label: str | None = None
    enabled: bool | None = None


class RuleFromEvent(BaseModel):
    event_id: int
    field: Literal["app", "domain", "title"] = "app"
    category_key: str


# ---- devices -----------------------------------------------------------------
class DeviceIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str
    kind: Literal["mac", "windows", "linux", "iphone", "watch", "other"] = "mac"
    is_work: bool = False
    monitoring_approved: bool = False
    collection_enabled: bool = True
    store_titles: bool = False
    aggregate_only: bool = False


class DevicePatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    is_work: bool | None = None
    monitoring_approved: bool | None = None
    collection_enabled: bool | None = None
    store_titles: bool | None = None
    aggregate_only: bool | None = None


# ---- goals/tasks -------------------------------------------------------------
class ProjectIn(BaseModel):
    name: str
    domain: str = "software"
    description: str = ""
    status: Literal["active", "paused", "done", "archived"] = "active"


class ProjectPatch(BaseModel):
    name: str | None = None
    domain: str | None = None
    description: str | None = None
    status: Literal["active", "paused", "done", "archived"] | None = None


class TaskIn(BaseModel):
    title: str
    description: str = ""
    domain: str = "software"
    project_id: int | None = None
    priority: int = Field(2, ge=1, le=4)
    estimate_minutes: int | None = None
    mental_demand: Demand = "medium"
    status: TaskStatus = "todo"
    due_date: date | None = None
    next_action: str = ""
    blocker: str = ""
    depends_on_id: int | None = None
    milestones: list[str] = []


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    domain: str | None = None
    project_id: int | None = None
    priority: int | None = Field(None, ge=1, le=4)
    estimate_minutes: int | None = None
    mental_demand: Demand | None = None
    status: TaskStatus | None = None
    due_date: date | None = None
    next_action: str | None = None
    blocker: str | None = None
    depends_on_id: int | None = None


class MilestoneIn(BaseModel):
    title: str


class MilestonePatch(BaseModel):
    title: str | None = None
    done: bool | None = None
    sort_order: int | None = None


class GoalIn(BaseModel):
    week_start: date | None = None
    domain: str
    title: str
    measure: Measure = "manual"
    target: float = Field(1, gt=0)
    checkin_kind: str | None = None
    notes: str = ""


class GoalPatch(BaseModel):
    domain: str | None = None
    title: str | None = None
    measure: Measure | None = None
    target: float | None = Field(None, gt=0)
    manual_progress: float | None = Field(None, ge=0)
    checkin_kind: str | None = None
    notes: str | None = None


# ---- sessions ----------------------------------------------------------------
class SessionIn(BaseModel):
    project: str = ""
    objective: str = ""
    task_id: int | None = None
    device_id: str | None = None
    client: Literal["claude_code", "desktop", "browser", "other"] = "claude_code"
    state: SessionState = "generating"
    priority: int = Field(2, ge=1, le=4)
    expected_next_action: str = ""
    notes: str = ""


class SessionPatch(BaseModel):
    project: str | None = None
    objective: str | None = None
    task_id: int | None = None
    device_id: str | None = None
    client: Literal["claude_code", "desktop", "browser", "other"] | None = None
    priority: int | None = Field(None, ge=1, le=4)
    expected_next_action: str | None = None
    notes: str | None = None


class SessionStateIn(BaseModel):
    state: SessionState | None = None
    needs_attention: bool | None = None


# ---- check-ins, reviews, trading --------------------------------------------
class CheckinIn(_UTC):
    domain: str
    kind: str
    title: str = ""
    note: str = ""
    value: float | None = None
    at: datetime | None = None
    project_name: str | None = None
    details: dict[str, Any] = {}


class ReviewIn(BaseModel):
    scripture_prayer: bool | None = None
    service_action: bool | None = None
    music_progress: bool | None = None
    learned: str = ""
    energy: int | None = Field(None, ge=1, le=5)
    tracker_issues: str = ""
    note: str = ""


class TradingNoteIn(BaseModel):
    day: date | None = None
    instrument: str = ""
    followed_plan: bool | None = None
    risk_sized: bool | None = None
    reason_recorded: bool | None = None
    rules_followed: bool | None = None
    intentional_time: bool | None = None
    entry_reason: str = ""
    exit_reason: str = ""
    note: str = ""


class SummaryIn(BaseModel):
    device_id: str
    day: date
    entries: list[dict[str, Any]]
    note: str = ""


class PathIn(BaseModel):
    path: str


class FeedbackIn(BaseModel):
    key: str
    kind: str
    title: str
    reason: str = ""
    action: Literal["accepted", "dismissed", "snoozed"]
    snooze_minutes: int | None = 30


class PauseIn(BaseModel):
    paused: bool
