"""Add media_id column to tweet_drafts.

Revision ID: b2c3d4e5f6a7
Revises: c9e8d4a1b3f7
Create Date: 2026-04-26 14:00:00.000000

Phase B engagement upgrade: store the X v1.1 media_id_string at queue time so
the admin Post button attaches the OG hero image to the live tweet (2-3×
engagement lift per industry literature).

Nullable on purpose — image fetch / upload is best-effort; a NULL value
means "post as text-only", not a broken row. RCA-007 (server_default for
NOT NULL on SQLite) does not apply here.

Parent chain note: Phase B's tweet_drafts table landed at a1b9c2d3e4f5,
but S45's per-channel email split (b8d4f1e2a637) and notify_new_courses
4th channel (c9e8d4a1b3f7) committed after Phase B in branch order, so the
true head at S47 start is c9e8d4a1b3f7. The S47 prompt's parent reference
was based on an `alembic current` snapshot taken before S45's migrations
were merged.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: str = "c9e8d4a1b3f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tweet_drafts",
        sa.Column("media_id", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tweet_drafts", "media_id")
