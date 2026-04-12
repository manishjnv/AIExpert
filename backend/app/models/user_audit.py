"""Audit log for user profile changes — tracks every write to User fields."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryKeyMixin


class UserAuditLog(PrimaryKeyMixin, Base):
    __tablename__ = "user_audit_log"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    field: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # profile_patch, google_login, otp_verify, admin
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    __table_args__ = (
        Index("ix_user_audit_user_id_changed_at", "user_id", "changed_at"),
    )
