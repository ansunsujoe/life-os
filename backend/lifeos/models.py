"""SQLAlchemy ORM models.

All datetimes are naive UTC (see `lifeos.timeutil`). Dates (`date`) are local
calendar dates in the user's configured timezone.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lifeos.db import Base
from lifeos.timeutil import utcnow


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32), default="mac")  # mac|windows|iphone|watch|other
    is_work: Mapped[bool] = mapped_column(Boolean, default=False)
    # Work devices stay unmonitored until the user explicitly confirms policy allows it.
    monitoring_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    collection_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    store_titles: Mapped[bool] = mapped_column(Boolean, default=True)
    # Work devices default to aggregate-only ingestion (category durations, no app/title).
    aggregate_only: Mapped[bool] = mapped_column(Boolean, default=False)
    # Remote collector auth: only a SHA-256 hash of the device token is stored.
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collector_info: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def content_free(self) -> bool:
        """Work devices only ever contribute categories and times — no titles,
        sites, app or project names — regardless of other flags."""
        return self.is_work or self.aggregate_only


class ActivityCategory(Base):
    __tablename__ = "activity_categories"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    color: Mapped[str] = mapped_column(String(16), default="gray")
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Productive domains count towards "meaningful progress" / intentionality.
    is_productive: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ClassificationRule(Base):
    __tablename__ = "classification_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower = evaluated first
    field: Mapped[str] = mapped_column(String(16))  # app|title|domain|url|any
    match_type: Mapped[str] = mapped_column(String(16), default="contains")  # contains|equals|regex
    pattern: Mapped[str] = mapped_column(String(512))
    category_key: Mapped[str] = mapped_column(ForeignKey("activity_categories.key"))
    confidence: Mapped[str] = mapped_column(String(8), default="medium")  # high|medium|low
    activity_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (
        Index("ix_activity_events_start", "start_time"),
        Index("ix_activity_events_device_start", "device_id", "start_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stable identifier from the source, used for dedup/upsert and auditing.
    source_key: Mapped[str] = mapped_column(String(256), unique=True)
    source: Mapped[str] = mapped_column(String(32))  # activitywatch|apple_health|robinhood_csv|manual|filesystem|claude_hook|manual_summary
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    app: Mapped[str | None] = mapped_column(String(256), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(String(256), nullable=True)
    activity: Mapped[str] = mapped_column(String(256), default="")
    category_key: Mapped[str] = mapped_column(String(32), default="other")
    subcategory: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[str] = mapped_column(String(8), default="low")
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Set by sequence analysis (e.g. rapid video hopping → "drift"). Overrides
    # the per-event rule category but never a user correction.
    pattern_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # User corrections survive re-ingestion and reclassification.
    category_override: Mapped[str | None] = mapped_column(String(32), nullable=True)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def effective_category(self) -> str:
        return self.category_override or self.pattern_category or self.category_key

    @property
    def effective_subcategory(self) -> str | None:
        if self.category_override and self.category_override != self.category_key:
            return None  # the rule's subcategory no longer applies
        if self.pattern_category == "drift" and not self.category_override:
            return "Quick hopping"
        return self.subcategory

    @property
    def effective_confidence(self) -> str:
        return "high" if (self.category_override or self.confirmed) else self.confidence

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.end_time - self.start_time).total_seconds())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    domain: Mapped[str] = mapped_column(String(32), default="software")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|paused|done|archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(32), default="software")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 low, 2 normal, 3 high, 4 urgent
    estimate_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mental_demand: Mapped[str] = mapped_column(String(8), default="medium")  # low|medium|high
    status: Mapped[str] = mapped_column(String(16), default="todo")  # todo|in_progress|blocked|done|dropped
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_action: Mapped[str] = mapped_column(Text, default="")
    blocker: Mapped[str] = mapped_column(Text, default="")
    depends_on_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    milestones: Mapped[list[TaskMilestone]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskMilestone.sort_order"
    )


class TaskMilestone(Base):
    __tablename__ = "task_milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(256))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    task: Mapped[Task] = relationship(back_populates="milestones")


class WeeklyGoal(Base):
    __tablename__ = "weekly_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_start: Mapped[date] = mapped_column(Date)  # Monday
    domain: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(256))
    # How progress is measured: manual|milestones|tasks_completed|checkins|workouts|activity_minutes
    measure: Mapped[str] = mapped_column(String(32), default="manual")
    target: Mapped[float] = mapped_column(Float, default=1.0)
    manual_progress: Mapped[float] = mapped_column(Float, default=0.0)
    checkin_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)  # optional filter for `checkins`
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ClaudeSession(Base):
    __tablename__ = "claude_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    project: Mapped[str] = mapped_column(String(128), default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client: Mapped[str] = mapped_column(String(16), default="claude_code")  # claude_code|desktop|browser|other
    state: Mapped[str] = mapped_column(String(16), default="ready")  # generating|ready|blocked|waiting|paused|completed
    needs_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=2)
    expected_next_action: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    cwd: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual|claude_hook
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_interaction_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    attention_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SessionStateChange(Base):
    __tablename__ = "session_state_changes"
    __table_args__ = (Index("ix_session_changes_at", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("claude_sessions.id", ondelete="CASCADE"))
    from_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_state: Mapped[str] = mapped_column(String(16))
    needs_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(16), default="manual")


class Checkin(Base):
    """Lightweight user-confirmed entries: faith practice, learning checkpoints,
    music milestones, manual workouts, breaks, energy, etc. Always high confidence."""

    __tablename__ = "checkins"
    __table_args__ = (Index("ix_checkins_at", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    domain: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(256), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    project_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual|daily_review


class HealthMetric(Base):
    __tablename__ = "health_metrics"
    __table_args__ = (Index("ix_health_metrics_start", "start_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(256), unique=True)
    metric: Mapped[str] = mapped_column(String(32))  # workout|steps|exercise_minutes|active_energy|sleep_minutes
    day: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(16), default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.id"), nullable=True)


class TradingEvent(Base):
    __tablename__ = "trading_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(128), unique=True)
    activity_date: Mapped[date] = mapped_column(Date)
    settle_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    instrument: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    trans_code: Mapped[str] = mapped_column(String(16), default="")
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.id"), nullable=True)


class TradingNote(Base):
    """Process-quality review for a trade or trading session. P&L is deliberately absent."""

    __tablename__ = "trading_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    instrument: Mapped[str] = mapped_column(String(32), default="")
    followed_plan: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    risk_sized: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reason_recorded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rules_followed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    intentional_time: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    entry_reason: Mapped[str] = mapped_column(Text, default="")
    exit_reason: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MusicSignal(Base):
    """File-system evidence from music project folders (context, not progress)."""

    __tablename__ = "music_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(512), unique=True)
    project_name: Mapped[str] = mapped_column(String(256))
    path: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))  # project_saved|project_created|bounce
    at: Mapped[datetime] = mapped_column(DateTime)


class DailyReview(Base):
    __tablename__ = "daily_reviews"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    scripture_prayer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    service_action: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    music_progress: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    learned: Mapped[str] = mapped_column(Text, default="")
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..5
    tracker_issues: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class RecommendationFeedback(Base):
    """Recommendations are computed on demand; only the user's response is stored."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rec_key: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(String(16))  # accepted|dismissed|snoozed
    snooze_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserSetting(Base):
    __tablename__ = "user_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ImportRun(Base):
    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # activitywatch|apple_health|robinhood_csv|music_scan|activity_json|manual_summary
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|ok|error
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_added: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    # Sanitised message only — never raw source contents (spec §11.5).
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CollectorStatus(Base):
    __tablename__ = "collector_status"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "activitywatch"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
