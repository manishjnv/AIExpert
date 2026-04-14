"""Add jobs, job_sources, job_companies tables for the AI Jobs module.

Revision ID: c8e2d15a3f97
Revises: b3f5a9e21c04
Create Date: 2026-04-14 10:00:00.000000

Design: docs/JOBS.md §3.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8e2d15a3f97"
down_revision: str = "b3f5a9e21c04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("external_id", sa.String, nullable=False),
        sa.Column("source_url", sa.String, nullable=False),
        sa.Column("hash", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="draft"),
        sa.Column("reject_reason", sa.String, nullable=True),
        sa.Column("posted_on", sa.Date, nullable=False),
        sa.Column("valid_through", sa.Date, nullable=False),
        sa.Column("last_reviewed_on", sa.Date, nullable=True),
        sa.Column("last_reviewed_by", sa.String, nullable=True),
        sa.Column("slug", sa.String, nullable=False, unique=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("company_slug", sa.String, nullable=False),
        sa.Column("designation", sa.String, nullable=False),
        sa.Column("country", sa.String, nullable=True),
        sa.Column("remote_policy", sa.String, nullable=True),
        sa.Column("verified", sa.Integer, nullable=False, server_default="0"),
        sa.Column("data", sa.JSON, nullable=False),
        sa.Column("admin_notes", sa.Text, nullable=True),
        sa.UniqueConstraint("source", "external_id", name="uq_job_source_external_id"),
    )
    op.create_index("ix_job_status_posted_on", "jobs", ["status", "posted_on"])
    op.create_index("ix_job_hash", "jobs", ["hash"])
    op.create_index("ix_job_company_slug", "jobs", ["company_slug"])
    op.create_index("ix_job_designation", "jobs", ["designation"])
    op.create_index("ix_job_country", "jobs", ["country"])

    op.create_table(
        "job_sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("key", sa.String, nullable=False, unique=True),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("label", sa.String, nullable=False),
        sa.Column("tier", sa.Integer, nullable=False, server_default="2"),
        sa.Column("enabled", sa.Integer, nullable=False, server_default="1"),
        sa.Column("bulk_approve", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime, nullable=True),
        sa.Column("last_run_fetched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_run_new", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_run_error", sa.Text, nullable=True),
        sa.Column("total_published", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_rejected", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "job_companies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("slug", sa.String, nullable=False, unique=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("size", sa.String, nullable=False, server_default="Unknown"),
        sa.Column("logo_url", sa.String, nullable=True),
        sa.Column("website", sa.String, nullable=True),
        sa.Column("verified", sa.Integer, nullable=False, server_default="0"),
        sa.Column("blocklisted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("blocklist_reason", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("job_companies")
    op.drop_table("job_sources")
    op.drop_index("ix_job_country", table_name="jobs")
    op.drop_index("ix_job_designation", table_name="jobs")
    op.drop_index("ix_job_company_slug", table_name="jobs")
    op.drop_index("ix_job_hash", table_name="jobs")
    op.drop_index("ix_job_status_posted_on", table_name="jobs")
    op.drop_table("jobs")
