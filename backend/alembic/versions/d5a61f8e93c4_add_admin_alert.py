"""Add admin_alert table for proactive cost-tracking alerts.

Revision ID: d5a61f8e93c4
Revises: c7d19e8a4f63
Create Date: 2026-04-12 23:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5a61f8e93c4"
down_revision: str = "c7d19e8a4f63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_alert",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("key", sa.String, nullable=False),
        sa.Column("severity", sa.String, nullable=False, server_default="warn"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("kind", "key", name="uq_admin_alert_kind_key"),
    )
    op.create_index("ix_admin_alert_resolved", "admin_alert", ["resolved_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_alert_resolved", "admin_alert")
    op.drop_table("admin_alert")
