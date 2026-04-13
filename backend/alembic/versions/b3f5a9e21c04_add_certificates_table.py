"""Add certificates table.

Revision ID: b3f5a9e21c04
Revises: a8c2e4f17b92
Create Date: 2026-04-13 08:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3f5a9e21c04"
down_revision: str = "a8c2e4f17b92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_plan_id", sa.Integer, sa.ForeignKey("user_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_key", sa.String, nullable=False),
        sa.Column("credential_id", sa.String, nullable=False, unique=True),
        sa.Column("tier", sa.String, nullable=False, server_default="completion"),
        sa.Column("display_name", sa.String, nullable=False),
        sa.Column("course_title", sa.String, nullable=False),
        sa.Column("level", sa.String, nullable=False),
        sa.Column("duration_months", sa.Integer, nullable=False),
        sa.Column("total_hours", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checks_done", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checks_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("repos_linked", sa.Integer, nullable=False, server_default="0"),
        sa.Column("repos_required", sa.Integer, nullable=False, server_default="0"),
        sa.Column("issued_at", sa.DateTime, nullable=False),
        sa.Column("signed_hash", sa.String, nullable=False),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("revoke_reason", sa.Text, nullable=True),
        sa.Column("pdf_downloads", sa.Integer, nullable=False, server_default="0"),
        sa.Column("linkedin_shares", sa.Integer, nullable=False, server_default="0"),
        sa.Column("verification_views", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "user_plan_id", name="uq_certificate_user_plan"),
    )
    op.create_index("ix_certificate_user_id", "certificates", ["user_id"])
    op.create_index("ix_certificate_credential_id", "certificates", ["credential_id"])


def downgrade() -> None:
    op.drop_index("ix_certificate_credential_id", "certificates")
    op.drop_index("ix_certificate_user_id", "certificates")
    op.drop_table("certificates")
