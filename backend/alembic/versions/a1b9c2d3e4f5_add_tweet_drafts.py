"""Add tweet_drafts table for daily X auto-post queue.

Revision ID: a1b9c2d3e4f5
Revises: c8e2d15a3f97
Create Date: 2026-04-26 10:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b9c2d3e4f5"
down_revision: str = "c8e2d15a3f97"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tweet_drafts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        # IST date the draft was queued for (display-friendly; e.g. '2026-04-26').
        sa.Column("scheduled_date", sa.String, nullable=False),
        # Slot type the curator picked: 'blog_teaser' | 'quotable' (more later).
        sa.Column("slot_type", sa.String, nullable=False),
        # Source kind + ref so we can dedupe ("don't repost the same blog within
        # 30 days") and link the live tweet back to the post in the admin UI.
        sa.Column("source_kind", sa.String, nullable=False),  # 'blog' for now
        sa.Column("source_ref", sa.String, nullable=False),   # blog slug
        sa.Column("draft_text", sa.Text, nullable=False),
        # 'pending' | 'posted' | 'skipped' | 'failed'
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        # X tweet id once posted; admin UI builds the live URL from this.
        sa.Column("posted_tweet_id", sa.String, nullable=True),
        sa.Column("posted_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    # Admin list view sorts by created_at desc with no filter; status filter
    # is occasional. Composite (status, created_at) covers both.
    op.create_index(
        "ix_tweet_drafts_status_created",
        "tweet_drafts",
        ["status", "created_at"],
    )
    # Curator dedupe lookup filters by (slot_type, status) and reads
    # source_ref + posted_at as projected columns. SQLite's query planner
    # picks the leftmost prefix, so this index covers both the in-flight
    # branch (status IN ...) and the recent-posted branch (status='posted').
    op.create_index(
        "ix_tweet_drafts_slot_status",
        "tweet_drafts",
        ["slot_type", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_tweet_drafts_slot_status", "tweet_drafts")
    op.drop_index("ix_tweet_drafts_status_created", "tweet_drafts")
    op.drop_table("tweet_drafts")
