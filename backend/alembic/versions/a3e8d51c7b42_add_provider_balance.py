"""Add provider_balance table, seed defaults from PROVIDER_INFO.

Revision ID: a3e8d51c7b42
Revises: f9b2c3d47a18
Create Date: 2026-04-12 21:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3e8d51c7b42"
down_revision: str = "f9b2c3d47a18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED = [
    ("openai", 10.00, 0.50, "Embeddings only"),
    ("gemini", 12.00, 0.40, "Generation + review + refine (free tier first)"),
    ("anthropic", 10.00, 0.50, "Surgical refinement only"),
    ("groq", 0.0, 0.0, "Free tier"),
    ("cerebras", 0.0, 0.0, "Free tier"),
    ("mistral", 0.0, 0.0, "Free tier"),
    ("sambanova", 0.0, 0.0, "Free tier"),
    ("deepseek", 0.0, 0.0, "Free tier (currently 402)"),
]


def upgrade() -> None:
    op.create_table(
        "provider_balance",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("provider", sa.String, nullable=False, unique=True),
        sa.Column("balance_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("recommended_cap_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
    )

    # Seed defaults
    now = sa.func.now()
    pb = sa.table(
        "provider_balance",
        sa.column("created_at"), sa.column("updated_at"),
        sa.column("provider"), sa.column("balance_usd"),
        sa.column("recommended_cap_usd"), sa.column("notes"),
    )
    op.bulk_insert(pb, [
        {
            "created_at": None, "updated_at": None,
            "provider": p, "balance_usd": b,
            "recommended_cap_usd": c, "notes": n,
        }
        for p, b, c, n in SEED
    ])
    # SQLite needs concrete timestamps, not func.now()
    op.execute(
        "UPDATE provider_balance SET created_at = CURRENT_TIMESTAMP, "
        "updated_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
    )


def downgrade() -> None:
    op.drop_table("provider_balance")
