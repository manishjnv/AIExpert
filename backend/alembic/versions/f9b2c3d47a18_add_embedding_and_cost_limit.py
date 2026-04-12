"""Add embedding column on discovered_topics and ai_cost_limit table.

Revision ID: f9b2c3d47a18
Revises: e7b3a1f45c2d
Create Date: 2026-04-12 20:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9b2c3d47a18"
down_revision: str = "e7b3a1f45c2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Semantic-dedup embedding on discovered_topics
    with op.batch_alter_table("discovered_topics") as batch:
        batch.add_column(sa.Column("embedding", sa.LargeBinary, nullable=True))

    # 2. Daily cost-cap table (per provider/model)
    op.create_table(
        "ai_cost_limit",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("provider", sa.String, nullable=False),
        sa.Column("model", sa.String, nullable=False, server_default="*"),
        sa.Column("daily_cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("daily_token_limit", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.UniqueConstraint("provider", "model", name="uq_ai_cost_limit_provider_model"),
    )


def downgrade() -> None:
    op.drop_table("ai_cost_limit")
    with op.batch_alter_table("discovered_topics") as batch:
        batch.drop_column("embedding")
