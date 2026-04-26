"""split email_notifications into per-channel toggles (jobs / roadmap / blog)

Revision ID: b8d4f1e2a637
Revises: a1b9c2d3e4f5
Create Date: 2026-04-26 12:00:00.000000

Replaces the single users.email_notifications boolean with three independent
channel toggles so a user can opt in or out of each weekly-digest section
separately. Existing opt-outs are preserved (email_notifications=0 maps to
all three channels off); existing opt-ins map to all three channels on,
which matches the prior default. Unambiguous downgrade rule: re-collapse
to email_notifications=0 only when ALL three channels are off.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d4f1e2a637"
down_revision: str = "a1b9c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: add three new columns. server_default=1 keeps existing rows
    # opted-in by default (matches the prior email_notifications default).
    # Per RCA-007, NOT NULL adds on SQLite require server_default.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            "notify_jobs", sa.Boolean(),
            nullable=False, server_default=sa.text("1"),
        ))
        batch_op.add_column(sa.Column(
            "notify_roadmap", sa.Boolean(),
            nullable=False, server_default=sa.text("1"),
        ))
        batch_op.add_column(sa.Column(
            "notify_blog", sa.Boolean(),
            nullable=False, server_default=sa.text("1"),
        ))

    # Step 2: preserve existing opt-outs. Anyone with email_notifications=0
    # had explicitly opted out — keep them off across all three channels.
    # Runs between the two batch blocks so both old and new columns coexist.
    op.execute(
        "UPDATE users SET notify_jobs = 0, notify_roadmap = 0, notify_blog = 0 "
        "WHERE email_notifications = 0"
    )

    # Step 3: drop the old single-toggle column.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("email_notifications")


def downgrade() -> None:
    # Re-add email_notifications with the prior default. Then collapse the
    # three channels back: only flip to 0 when ALL three are off (the only
    # state that maps unambiguously to "opted out of everything").
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            "email_notifications", sa.Boolean(),
            nullable=False, server_default=sa.text("1"),
        ))

    op.execute(
        "UPDATE users SET email_notifications = 0 "
        "WHERE notify_jobs = 0 AND notify_roadmap = 0 AND notify_blog = 0"
    )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("notify_jobs")
        batch_op.drop_column("notify_roadmap")
        batch_op.drop_column("notify_blog")
