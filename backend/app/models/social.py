"""SocialPost — AI-curated social media drafts (Phase G).

One row per (source_kind, source_slug, platform) pair in an active state.
The partial UNIQUE index in the migration prevents double-queueing.

Status machine (§3.11 AI_PIPELINE_PLAN.md):
  pending → draft → published  (terminal)
  draft   → archived           (admin discard or 30-day auto-archive)
  pending → archived           (3× validation failure)

No FK relationships to blog/course tables — sources are loose-coupled by
`source_slug` string to avoid cross-module schema coupling.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Text, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryKeyMixin

# ---------------------------------------------------------------------------
# Module-level constants — single source of truth for allowed values.
# CHECK constraints in the migration are the enforcement gate; these
# constants drive application-layer guards and test fixtures.
# ---------------------------------------------------------------------------

SOURCE_KINDS = ("blog", "course")
PLATFORMS = ("twitter", "linkedin")
STATUSES = ("pending", "draft", "published", "archived")


class SocialPost(PrimaryKeyMixin, Base):
    """ORM model for the social_posts table."""

    __tablename__ = "social_posts"

    # Source identity — loose-coupled by slug string, no FK.
    source_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="blog | course"
    )
    source_slug: Mapped[str] = mapped_column(String(200), nullable=False)

    # Platform for this draft.
    platform: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="twitter | linkedin"
    )

    # Lifecycle status. Allowed values in STATUSES constant above.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )

    # Draft content — nullable until Opus call completes and Pydantic validates.
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON-serialised list[str] of canonical hashtags.
    hashtags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON-serialised ReasoningTrail object (§4 invariant #4).
    reasoning_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Validation retry counter — pending → archived after 3 failures.
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # URL of the live post; set on the "Mark as posted" admin action.
    published_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps — use TIMESTAMP to match migration DDL type.
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )
