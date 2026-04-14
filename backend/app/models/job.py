"""AI Jobs — scraped, AI-enriched, admin-reviewed job postings.

See docs/JOBS.md for full design. One row per (source, external_id). Admin-gated
publish: ingest always stages rows as `draft`; only an admin action flips
status to `published`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryKeyMixin, TimestampMixin


class Job(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    # Source identity — (source, external_id) is the natural key.
    source: Mapped[str] = mapped_column(String, nullable=False)          # greenhouse|lever|yc|rss:<slug>
    external_id: Mapped[str] = mapped_column(String, nullable=False)     # stable id from source
    source_url: Mapped[str] = mapped_column(String, nullable=False)      # apply URL on source ATS

    # SHA256 of normalized (title|company|location|jd). Drives change detection
    # and cross-source dedup.
    hash: Mapped[str] = mapped_column(String, nullable=False)

    # Lifecycle. Off-list values rejected at service layer.
    # draft | published | rejected | expired
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")

    # Rejection reason (enum, see docs/JOBS.md §10.3) — feeds extractor feedback loop.
    reject_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Original source publish date — NOT scrape date. Drives SEO + age filters.
    posted_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Auto-expire date (default posted_on + 45d; admin-editable).
    valid_through: Mapped[date] = mapped_column(Date, nullable=False)

    # Admin review stamps — mirrors the template publish-gate pattern.
    last_reviewed_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_reviewed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # URL slug — `<designation>-at-<company>-<shortid>`. Unique, stable.
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    # Denormalized columns for cheap filtering/sorting without opening `data`.
    # Full payload always lives in `data`; these mirror a subset.
    title: Mapped[str] = mapped_column(String, nullable=False)
    company_slug: Mapped[str] = mapped_column(String, nullable=False)
    designation: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # ISO-2
    remote_policy: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 1 if Tier-1 source

    # Full enriched payload (schema in docs/JOBS.md §3.2).
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Admin-only free-text for review notes / flag reasons.
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_source_external_id"),
        Index("ix_job_status_posted_on", "status", "posted_on"),
        Index("ix_job_hash", "hash"),
        Index("ix_job_company_slug", "company_slug"),
        Index("ix_job_designation", "designation"),
        Index("ix_job_country", "country"),
    )


class JobSource(PrimaryKeyMixin, TimestampMixin, Base):
    """One row per ingestion source. Admin can toggle, blocklist, track stats."""

    __tablename__ = "job_sources"

    # Stable key used in Job.source (e.g. 'greenhouse:anthropic').
    key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)       # greenhouse|lever|yc|rss
    label: Mapped[str] = mapped_column(String, nullable=False)      # "Anthropic (Greenhouse)"
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=2)  # 1=verified, 2=aggregated
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    bulk_approve: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # Tier-1 only

    # Per-run stats (cumulative; daily deltas derived from ingest logs).
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_run_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    total_published: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class JobCompany(PrimaryKeyMixin, TimestampMixin, Base):
    """Company registry — logo, size, verified flag, blocklist."""

    __tablename__ = "job_companies"

    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    size: Mapped[str] = mapped_column(String, nullable=False, default="Unknown")
    logo_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocklisted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocklist_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
