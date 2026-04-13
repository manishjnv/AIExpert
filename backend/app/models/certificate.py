"""Course completion certificates issued to users who finish a plan.

One certificate per (user_id, user_plan_id). Idempotent — re-triggering the
issuance on a plan that already has a certificate returns the existing row.
Re-enrolling in the same template keeps the original certificate (with its
original issued_at date).

Tier logic lives in services/certificates.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import PrimaryKeyMixin


class Certificate(PrimaryKeyMixin, Base):
    __tablename__ = "certificates"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("user_plans.id", ondelete="CASCADE"), nullable=False)
    template_key: Mapped[str] = mapped_column(String, nullable=False)

    # Public-facing credential ID. Format: AER-YYYY-MM-XXXXXX (6 alphanumeric).
    # Embedded in QR + verify URL; safe to expose on LinkedIn.
    credential_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    # Tier gating is enforced at issuance time in the service layer.
    # 'completion' | 'distinction' | 'honors'
    tier: Mapped[str] = mapped_column(String, nullable=False, default="completion")

    # Name snapshotted at issue time — editing profile.name later does NOT
    # retro-update issued certificates. Admin can re-issue if needed.
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    course_title: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[str] = mapped_column(String, nullable=False)
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False)

    # Point-in-time stats baked into the cert body
    total_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checks_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repos_linked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repos_required: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    # HMAC over (credential_id, user_id, issued_at) with server secret —
    # powers the 'verified authentic' badge on the public page.
    signed_hash: Mapped[str] = mapped_column(String, nullable=False)

    # Lifecycle
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Analytics
    pdf_downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    linkedin_shares: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "user_plan_id", name="uq_certificate_user_plan"),
        Index("ix_certificate_user_id", "user_id"),
        Index("ix_certificate_credential_id", "credential_id"),
    )
