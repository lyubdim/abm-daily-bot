"""Create the initial ABM Daily Bot schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def timestamp_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("odoo_user_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "task_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("odoo_task_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("project_name", sa.String(255)),
        sa.Column("stage_id", sa.Integer()),
        sa.Column("stage_name", sa.String(255)),
        sa.Column("deadline", sa.Date()),
        sa.Column("task_url", sa.String(1000)),
        sa.Column("assignee_odoo_ids", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "daily_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("odoo_task_id", sa.Integer(), nullable=False),
        sa.Column("answer_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress_text", sa.Text()),
        sa.Column("selected_stage_id", sa.Integer()),
        sa.Column("selected_state", sa.String(50)),
        sa.Column("result_url", sa.String(1000)),
        *timestamp_columns(),
        sa.UniqueConstraint("user_id", "odoo_task_id", "answer_date", name="uq_daily_answer"),
    )
    op.create_table(
        "daily_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("summary_date", sa.Date(), nullable=False),
        sa.Column("extra_text", sa.Text()),
        *timestamp_columns(),
        sa.UniqueConstraint("user_id", "summary_date", name="uq_daily_summary"),
    )
    op.create_table(
        "weekly_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("focus_task_ids", sa.JSON(), nullable=False),
        sa.Column("strategic_text", sa.Text()),
        *timestamp_columns(),
        sa.UniqueConstraint("user_id", "week_start", name="uq_weekly_plan"),
    )
    op.create_table(
        "blockers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("odoo_task_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_url", sa.String(1000)),
        sa.Column("escalated_at", sa.DateTime(timezone=True)),
        *timestamp_columns(),
    )
    op.create_index("ix_blockers_odoo_task_id", "blockers", ["odoo_task_id"])
    op.create_table(
        "ai_advices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("blocker_id", sa.Integer(), sa.ForeignKey("blockers.id"), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("clarification_question", sa.Text()),
        sa.Column("model", sa.String(100), nullable=False),
        *timestamp_columns(),
    )
    op.create_table(
        "odoo_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("method", sa.String(100), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("keyword_arguments", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("remote_record_id", sa.Integer()),
        *timestamp_columns(),
    )
    op.create_table(
        "pm_digest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period_kind", sa.String(20), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipient_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        *timestamp_columns(),
    )


def downgrade() -> None:
    op.drop_table("pm_digest_runs")
    op.drop_table("odoo_outbox")
    op.drop_table("ai_advices")
    op.drop_index("ix_blockers_odoo_task_id", table_name="blockers")
    op.drop_table("blockers")
    op.drop_table("weekly_plans")
    op.drop_table("daily_summaries")
    op.drop_table("daily_answers")
    op.drop_table("task_cache")
    op.drop_table("users")

