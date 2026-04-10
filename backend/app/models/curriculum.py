"""PlanVersion, CurriculumProposal, and LinkHealth models — see DATA_MODEL.md."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryKeyMixin, TimestampMixin


class PlanVersion(PrimaryKeyMixin, Base):
    __tablename__ = "plan_versions"

    version: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    changes_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of strings
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CurriculumProposal(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "curriculum_proposals"

    source_run: Mapped[str] = mapped_column(String, nullable=False)
    proposal_md: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # pending/applied/rejected
    reviewer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_curriculum_proposals_status", "status"),
        Index("ix_curriculum_proposals_created_at", "created_at"),
    )


class LinkHealth(PrimaryKeyMixin, Base):
    __tablename__ = "link_health"

    template_key: Mapped[str] = mapped_column(String, nullable=False)
    week_num: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    last_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_link_health_template_week", "template_key", "week_num"),
    )
