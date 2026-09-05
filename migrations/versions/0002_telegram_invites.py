"""Add secure one-time Telegram onboarding invitations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_telegram_invites"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("odoo_user_id", sa.Integer(), nullable=False),
        sa.Column("odoo_display_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("used_by_telegram_user_id", sa.BigInteger()),
        sa.Column("used_at", sa.DateTime(timezone=True)),
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
    op.create_index(
        "ix_telegram_invites_odoo_user_id",
        "telegram_invites",
        ["odoo_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_invites_odoo_user_id", table_name="telegram_invites")
    op.drop_table("telegram_invites")
