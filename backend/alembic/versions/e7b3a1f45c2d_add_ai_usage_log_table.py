"""Add ai_usage_log table for tracking AI provider calls.

Revision ID: e7b3a1f45c2d
Revises: d4a1c8e92f3b
Create Date: 2026-04-11 16:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7b3a1f45c2d"
down_revision: str = "d4a1c8e92f3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("called_at", sa.DateTime, nullable=False),
        sa.Column("provider", sa.String, nullable=False),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("task", sa.String, nullable=False),
        sa.Column("subtask", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("tokens_estimated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_ai_usage_log_called_at", "ai_usage_log", ["called_at"])
    op.create_index("ix_ai_usage_log_provider", "ai_usage_log", ["provider"])
    op.create_index("ix_ai_usage_log_task", "ai_usage_log", ["task"])


def downgrade() -> None:
    op.drop_table("ai_usage_log")
