"""TweetDraft — daily-queued X/Twitter post drafts.

Lifecycle:
  curator (cron 8am IST) → status='pending'
  admin clicks "Post"     → twitter_client → status='posted' + posted_tweet_id
                                            ┘└→ status='failed' + error_message
  admin clicks "Skip"     → status='skipped'

Source dedupe: the curator joins on (source_kind, source_ref, status='posted')
within a 30-day lookback to avoid reposting the same item.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryKeyMixin, TimestampMixin


class TweetDraft(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tweet_drafts"

    scheduled_date: Mapped[str] = mapped_column(String, nullable=False)
    slot_type: Mapped[str] = mapped_column(String, nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    posted_tweet_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
