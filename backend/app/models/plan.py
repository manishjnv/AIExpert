"""UserPlan, Progress, RepoLink, and Evaluation models — see DATA_MODEL.md."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import PrimaryKeyMixin


class UserPlan(PrimaryKeyMixin, Base):
    __tablename__ = "user_plans"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    template_key: Mapped[str] = mapped_column(String, nullable=False)
    plan_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # active/archived/completed
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="plans")  # noqa: F821
    progress_items: Mapped[list[Progress]] = relationship(back_populates="user_plan", cascade="all, delete-orphan")
    repo_links: Mapped[list[RepoLink]] = relationship(back_populates="user_plan", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_user_plans_user_id", "user_id"),
    )


class Progress(PrimaryKeyMixin, Base):
    __tablename__ = "progress"

    user_plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("user_plans.id", ondelete="CASCADE"), nullable=False)
    week_num: Mapped[int] = mapped_column(Integer, nullable=False)
    check_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user_plan: Mapped[UserPlan] = relationship(back_populates="progress_items")

    __table_args__ = (
        UniqueConstraint("user_plan_id", "week_num", "check_idx", name="uq_progress_plan_week_check"),
        Index("ix_progress_user_plan_id", "user_plan_id"),
    )


class RepoLink(PrimaryKeyMixin, Base):
    __tablename__ = "repo_links"

    user_plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("user_plans.id", ondelete="CASCADE"), nullable=False)
    week_num: Mapped[int] = mapped_column(Integer, nullable=False)
    repo_owner: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    default_branch: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_commit_sha: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user_plan: Mapped[UserPlan] = relationship(back_populates="repo_links")
    evaluations: Mapped[list[Evaluation]] = relationship(back_populates="repo_link", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("user_plan_id", "week_num", name="uq_repo_links_plan_week"),
    )


class Evaluation(PrimaryKeyMixin, Base):
    __tablename__ = "evaluations"

    repo_link_id: Mapped[int] = mapped_column(Integer, ForeignKey("repo_links.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strengths_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of strings
    improvements_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of strings
    deliverable_met: Mapped[bool] = mapped_column(Boolean, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    repo_link: Mapped[RepoLink] = relationship(back_populates="evaluations")

    __table_args__ = (
        Index("ix_evaluations_repo_link_id", "repo_link_id"),
        Index("ix_evaluations_created_at", "created_at"),
    )
