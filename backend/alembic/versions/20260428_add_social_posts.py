"""Add social_posts table for AI-curated social post curation (Phase G).

Revision ID: 20260428000000
Revises: b2c3d4e5f6a7
Create Date: 2026-04-28 12:00:00.000000

§3.11 in AI_PIPELINE_PLAN.md. Stores Opus 4.7-generated Twitter + LinkedIn
drafts (one row per source × platform). Status machine:
  pending → draft → published  (terminal)
  draft   → archived           (admin discard or 30-day auto-archive)
  pending → archived           (3× validation failure)

UNIQUE partial index on (source_kind, source_slug, platform)
WHERE status IN ('pending', 'draft') prevents double-queueing.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260428000000"
down_revision: str = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "social_posts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "source_kind",
            sa.String(16),
            nullable=False,
            comment="blog | course",
        ),
        sa.Column("source_slug", sa.String(200), nullable=False),
        sa.Column(
            "platform",
            sa.String(16),
            nullable=False,
            comment="twitter | linkedin",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
            comment="pending | draft | published | archived",
        ),
        # Populated once the Opus call returns and Pydantic validation passes.
        sa.Column("body", sa.Text, nullable=True),
        # JSON-serialised list[str] of hashtags.
        sa.Column("hashtags_json", sa.Text, nullable=True),
        # JSON-serialised ReasoningTrail object.
        sa.Column("reasoning_json", sa.Text, nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        # URL of the live post (Twitter tweet URL or LinkedIn post URL set via
        # the "Mark as posted" flow).
        sa.Column("published_url", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("published_at", sa.TIMESTAMP, nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP, nullable=True),
        # CHECK constraints — SQLite enforces these at INSERT / UPDATE time.
        sa.CheckConstraint(
            "source_kind IN ('blog', 'course')",
            name="ck_social_posts_source_kind",
        ),
        sa.CheckConstraint(
            "platform IN ('twitter', 'linkedin')",
            name="ck_social_posts_platform",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'draft', 'published', 'archived')",
            name="ck_social_posts_status",
        ),
    )

    # Composite index: admin list + nightly-cron candidate scan both filter
    # on status first, then sort / filter on created_at.
    op.create_index(
        "ix_social_posts_status_created",
        "social_posts",
        ["status", "created_at"],
    )

    # Partial UNIQUE index: at most one active (pending/draft) row per
    # (source_kind, source_slug, platform) tuple, prevents double-queueing.
    # op.create_index does not support SQLite partial index WHERE clauses
    # reliably, so we use op.execute with raw DDL.
    op.execute(
        "CREATE UNIQUE INDEX uq_social_posts_active "
        "ON social_posts (source_kind, source_slug, platform) "
        "WHERE status IN ('pending', 'draft')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_social_posts_active")
    op.drop_index("ix_social_posts_status_created", table_name="social_posts")
    op.drop_table("social_posts")
