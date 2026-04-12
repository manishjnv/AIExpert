"""Curriculum models — PlanVersion, CurriculumProposal, LinkHealth, CurriculumSettings, DiscoveredTopic."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
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


class CurriculumSettings(PrimaryKeyMixin, TimestampMixin, Base):
    """Singleton admin config for the auto-curriculum pipeline."""

    __tablename__ = "curriculum_settings"

    # Discovery config
    max_topics_per_discovery: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    discovery_frequency: Mapped[str] = mapped_column(String, nullable=False, default="monthly")  # monthly/quarterly
    auto_approve_topics: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Generation config
    auto_generate_variants: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # AI model preferences
    ai_model_research: Mapped[str] = mapped_column(String, nullable=False, default="gemini")  # gemini/groq
    ai_model_formatting: Mapped[str] = mapped_column(String, nullable=False, default="groq")

    # Budget
    max_tokens_per_run: Mapped[int] = mapped_column(Integer, nullable=False, default=50000)
    tokens_used_this_month: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_month: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "2026-04"

    # Refresh config
    refresh_frequency: Mapped[str] = mapped_column(String, nullable=False, default="quarterly")

    # Timestamps for last runs
    last_discovery_run: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_generation_run: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_refresh_run: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AIUsageLog(PrimaryKeyMixin, Base):
    """Log of every AI provider call for usage tracking and admin dashboard."""

    __tablename__ = "ai_usage_log"

    # When
    called_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # What provider
    provider: Mapped[str] = mapped_column(String, nullable=False)  # gemini, groq, cerebras, etc.
    model: Mapped[str] = mapped_column(String, nullable=False)

    # What task
    task: Mapped[str] = mapped_column(String, nullable=False)  # discovery, triage, generation, chat, eval, refresh
    subtask: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # topic name, week, etc.

    # Result
    status: Mapped[str] = mapped_column(String, nullable=False)  # ok, rate_limited, error, timeout
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tokens_estimated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_ai_usage_log_called_at", "called_at"),
        Index("ix_ai_usage_log_provider", "provider"),
        Index("ix_ai_usage_log_task", "task"),
    )


class DiscoveredTopic(PrimaryKeyMixin, TimestampMixin, Base):
    """AI-discovered trending topic awaiting admin review."""

    __tablename__ = "discovered_topics"

    # Identity
    topic_name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # dedup key
    category: Mapped[str] = mapped_column(String, nullable=False)  # e.g. nlp, cv, mlops, rl, accel, accel_gen, accel_accel, accel_accel_accel
    subcategory: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # AI reasoning trail (per enrichment blueprint)
    justification: Mapped[str] = mapped_column(Text, nullable=False)  # why this topic is trending
    evidence_sources: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of source URLs/names
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=50)  # 0-100

    # Lifecycle state machine: pending → approved → generating → generated (or rejected)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")

    # Discovery metadata
    discovery_run: Mapped[str] = mapped_column(String, nullable=False)  # run ID (ISO timestamp)
    ai_model_used: Mapped[str] = mapped_column(String, nullable=False)

    # Review
    reviewer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Generation tracking
    templates_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generation_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Semantic dedup: OpenAI text-embedding-3-small vector (float32 packed).
    # Populated at discovery time; compared via cosine similarity against
    # future topics to catch near-duplicates that normalized_name misses.
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)

    __table_args__ = (
        Index("ix_discovered_topics_status", "status"),
        Index("ix_discovered_topics_category", "category"),
        Index("ix_discovered_topics_discovery_run", "discovery_run"),
    )


class AICostLimit(PrimaryKeyMixin, TimestampMixin, Base):
    """Admin-configured daily USD cost cap per provider/model.

    model='*' means the cap applies across all models for that provider.
    Checked before each paid provider call; exceeding blocks further calls
    for the rest of the UTC day.
    """

    __tablename__ = "ai_cost_limit"

    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False, default="*")
    daily_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    daily_token_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("provider", "model", name="uq_ai_cost_limit_provider_model"),
    )
