"""add notify_new_courses to users (4th digest channel)

Revision ID: c9e8d4a1b3f7
Revises: b8d4f1e2a637
Create Date: 2026-04-26 13:00:00.000000

Adds a 4th independent toggle alongside notify_jobs / notify_roadmap /
notify_blog. Fires when a curriculum template's _meta.json
last_reviewed_on date falls within the last 7 days (i.e. an admin just
published it). Default ON for new users — same opt-in posture as the
other three. Existing rows get default=1 via server_default per RCA-007.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e8d4a1b3f7"
down_revision: str = "b8d4f1e2a637"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            "notify_new_courses", sa.Boolean(),
            nullable=False, server_default=sa.text("1"),
        ))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("notify_new_courses")
