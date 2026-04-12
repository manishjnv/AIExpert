"""Add user_audit_log table.

Revision ID: a8c2e4f17b92
Revises: d5a61f8e93c4
Create Date: 2026-04-12 11:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8c2e4f17b92"
down_revision: str = "d5a61f8e93c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field", sa.String, nullable=False),
        sa.Column("old_value", sa.Text, nullable=True),
        sa.Column("new_value", sa.Text, nullable=True),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("changed_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_user_audit_user_id_changed_at", "user_audit_log", ["user_id", "changed_at"])


def downgrade() -> None:
    op.drop_index("ix_user_audit_user_id_changed_at", "user_audit_log")
    op.drop_table("user_audit_log")
