"""Add curriculum_settings and discovered_topics tables.

Revision ID: d4a1c8e92f3b
Revises: bcac9760e38f
Create Date: 2026-04-11 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4a1c8e92f3b"
down_revision: str = "bcac9760e38f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "curriculum_settings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("max_topics_per_discovery", sa.Integer, nullable=False, server_default="10"),
        sa.Column("discovery_frequency", sa.String, nullable=False, server_default="monthly"),
        sa.Column("auto_approve_topics", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("auto_generate_variants", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("ai_model_research", sa.String, nullable=False, server_default="gemini"),
        sa.Column("ai_model_formatting", sa.String, nullable=False, server_default="groq"),
        sa.Column("max_tokens_per_run", sa.Integer, nullable=False, server_default="50000"),
        sa.Column("tokens_used_this_month", sa.Integer, nullable=False, server_default="0"),
        sa.Column("budget_month", sa.String, nullable=True),
        sa.Column("refresh_frequency", sa.String, nullable=False, server_default="quarterly"),
        sa.Column("last_discovery_run", sa.DateTime, nullable=True),
        sa.Column("last_generation_run", sa.DateTime, nullable=True),
        sa.Column("last_refresh_run", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "discovered_topics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("topic_name", sa.String, nullable=False),
        sa.Column("normalized_name", sa.String, nullable=False, unique=True),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("subcategory", sa.String, nullable=True),
        sa.Column("justification", sa.Text, nullable=False),
        sa.Column("evidence_sources", sa.Text, nullable=False),
        sa.Column("confidence_score", sa.Integer, nullable=False, server_default="50"),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("discovery_run", sa.String, nullable=False),
        sa.Column("ai_model_used", sa.String, nullable=False),
        sa.Column("reviewer_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime, nullable=True),
        sa.Column("reviewer_notes", sa.Text, nullable=True),
        sa.Column("templates_generated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("generation_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_index("ix_discovered_topics_status", "discovered_topics", ["status"])
    op.create_index("ix_discovered_topics_category", "discovered_topics", ["category"])
    op.create_index("ix_discovered_topics_discovery_run", "discovered_topics", ["discovery_run"])


def downgrade() -> None:
    op.drop_index("ix_discovered_topics_discovery_run", table_name="discovered_topics")
    op.drop_index("ix_discovered_topics_category", table_name="discovered_topics")
    op.drop_index("ix_discovered_topics_status", table_name="discovered_topics")
    op.drop_table("discovered_topics")
    op.drop_table("curriculum_settings")
