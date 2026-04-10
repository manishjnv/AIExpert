"""User, OtpCode, and Session models — see DATA_MODEL.md."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import PrimaryKeyMixin, TimestampMixin


class User(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # "google" or "otp"
    provider_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    github_username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    learning_goal: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    experience_level: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # beginner/intermediate/advanced
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_seen_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    sessions: Mapped[list[Session]] = relationship(back_populates="user", cascade="all, delete-orphan")
    plans: Mapped[list] = relationship("UserPlan", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_users_provider_id", "provider_id"),
    )


class OtpCode(PrimaryKeyMixin, Base):
    __tablename__ = "otp_codes"

    email: Mapped[str] = mapped_column(String, nullable=False)
    code_hash: Mapped[str] = mapped_column(String, nullable=False)
    salt: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_otp_codes_email", "email"),
        Index("ix_otp_codes_expires_at", "expires_at"),
    )


class Session(PrimaryKeyMixin, Base):
    __tablename__ = "sessions"

    jti: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
    )
