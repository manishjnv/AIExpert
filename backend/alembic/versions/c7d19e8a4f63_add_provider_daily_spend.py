"""Add provider_daily_spend table for provider-authoritative usage reconciliation.

Revision ID: c7d19e8a4f63
Revises: a3e8d51c7b42
Create Date: 2026-04-12 22:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d19e8a4f63"
down_revision: str = "a3e8d51c7b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_daily_spend",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("day", sa.String, nullable=False),
        sa.Column("provider", sa.String, nullable=False),
        sa.Column("model", sa.String, nullable=False, server_default="*"),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd_provider", sa.Float, nullable=False, server_default="0"),
        sa.Column("cost_usd_local", sa.Float, nullable=False, server_default="0"),
        sa.Column("drift_pct", sa.Float, nullable=True),
        sa.Column("raw_response", sa.Text, nullable=True),
        sa.UniqueConstraint("day", "provider", "model",
                             name="uq_provider_daily_spend_day_provider_model"),
    )
    op.create_index("ix_provider_daily_spend_day", "provider_daily_spend", ["day"])
    op.create_index("ix_provider_daily_spend_provider", "provider_daily_spend", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_provider_daily_spend_provider", "provider_daily_spend")
    op.drop_index("ix_provider_daily_spend_day", "provider_daily_spend")
    op.drop_table("provider_daily_spend")
