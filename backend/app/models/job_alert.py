"""JobAlertSubscription — per-company job alert subscription (Phase 1: email).

One row per (user, company_slug, channel). The daily digest matches newly
published jobs' company_slug against active rows and emails each subscriber.
`__table_args__` mirrors the migration so Base.metadata.create_all (test path)
honors the same constraints + indexes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    TIMESTAMP,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class JobAlertSubscription(Base):
    __tablename__ = "job_alert_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, server_default="email")
    active: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint(
            "channel IN ('email', 'telegram', 'whatsapp')",
            name="ck_job_alert_sub_channel",
        ),
        UniqueConstraint(
            "user_id", "company_slug", "channel",
            name="uq_job_alert_sub_user_company_channel",
        ),
        Index("ix_job_alert_sub_company_active", "company_slug", "active"),
        Index("ix_job_alert_sub_user", "user_id"),
    )
