"""Add job_alert_subscriptions table — per-company job alerts (Phase 1, email).

Revision ID: 20260601000000
Revises: 20260428000000
Create Date: 2026-06-01 12:00:00.000000

See docs/HANDOFF.md / the JOB_ALERTS plan. One row per (user, company_slug,
channel). Phase 1 ships the email channel; telegram/whatsapp are reserved in
the CHECK so later phases need no migration. A daily digest emails each user
the new published jobs from the companies they follow.

UNIQUE(user_id, company_slug, channel) prevents duplicate subscriptions.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260601000000"
down_revision: str = "20260428000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_alert_subscriptions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Company to follow. Matches Job.company_slug / JobCompany.slug.
        sa.Column("company_slug", sa.String(120), nullable=False),
        sa.Column(
            "channel",
            sa.String(16),
            nullable=False,
            server_default="email",
            comment="email | telegram | whatsapp (only email active in Phase 1)",
        ),
        sa.Column(
            "active",
            sa.Integer,
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'telegram', 'whatsapp')",
            name="ck_job_alert_sub_channel",
        ),
        sa.UniqueConstraint(
            "user_id", "company_slug", "channel",
            name="uq_job_alert_sub_user_company_channel",
        ),
    )
    # Fan-out lookup: the daily digest matches new jobs' company_slug against
    # active subscriptions, so index (company_slug, active).
    op.create_index(
        "ix_job_alert_sub_company_active",
        "job_alert_subscriptions",
        ["company_slug", "active"],
    )
    # "My subscriptions" listing filters by user.
    op.create_index(
        "ix_job_alert_sub_user",
        "job_alert_subscriptions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_alert_sub_user", table_name="job_alert_subscriptions")
    op.drop_index("ix_job_alert_sub_company_active", table_name="job_alert_subscriptions")
    op.drop_table("job_alert_subscriptions")
