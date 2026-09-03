from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

from abm_daily_bot.domain import BlockerStatus, DailyAnswerStatus


class Base(DeclarativeBase):
    pass


class UserRole(StrEnum):
    MEMBER = "member"
    PM = "pm"
    TECH_LEAD = "tech_lead"


class OutboxState(StrEnum):
    PENDING = "pending"
    RETRY = "retry"
    SENT = "sent"
    FAILED = "failed"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    odoo_user_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False), default=UserRole.MEMBER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TaskCache(TimestampMixin, Base):
    __tablename__ = "task_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    odoo_task_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    project_name: Mapped[str | None] = mapped_column(String(255))
    stage_id: Mapped[int | None] = mapped_column(Integer)
    stage_name: Mapped[str | None] = mapped_column(String(255))
    deadline: Mapped[date | None] = mapped_column(Date)
    task_url: Mapped[str | None] = mapped_column(String(1000))
    assignee_odoo_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class DailyAnswer(TimestampMixin, Base):
    __tablename__ = "daily_answers"
    __table_args__ = (
        UniqueConstraint("user_id", "odoo_task_id", "answer_date", name="uq_daily_answer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    odoo_task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[DailyAnswerStatus] = mapped_column(
        Enum(DailyAnswerStatus, native_enum=False), nullable=False
    )
    progress_text: Mapped[str | None] = mapped_column(Text)
    selected_stage_id: Mapped[int | None] = mapped_column(Integer)
    result_url: Mapped[str | None] = mapped_column(String(1000))


class WeeklyPlan(TimestampMixin, Base):
    __tablename__ = "weekly_plans"
    __table_args__ = (UniqueConstraint("user_id", "week_start", name="uq_weekly_plan"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    focus_task_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    strategic_text: Mapped[str | None] = mapped_column(Text)


class Blocker(TimestampMixin, Base):
    __tablename__ = "blockers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    odoo_task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[BlockerStatus] = mapped_column(
        Enum(BlockerStatus, native_enum=False), default=BlockerStatus.OPEN, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_url: Mapped[str | None] = mapped_column(String(1000))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIAdvice(TimestampMixin, Base):
    __tablename__ = "ai_advices"

    id: Mapped[int] = mapped_column(primary_key=True)
    blocker_id: Mapped[int] = mapped_column(ForeignKey("blockers.id"), nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    clarification_question: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100), nullable=False)


class OdooOutbox(TimestampMixin, Base):
    __tablename__ = "odoo_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    keyword_arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[OutboxState] = mapped_column(
        Enum(OutboxState, native_enum=False), default=OutboxState.PENDING, nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class PMDigestRun(TimestampMixin, Base):
    __tablename__ = "pm_digest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recipient_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

