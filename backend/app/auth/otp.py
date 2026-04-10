"""
OTP code generation and verification for email sign-in.

Codes are 6 digits, hashed with SHA-256 + per-row salt, and expire after 10 minutes.
Max 5 verification attempts per code.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import OtpCode


def generate_code() -> str:
    """Generate a random 6-digit OTP code."""
    return "".join(secrets.choice("0123456789") for _ in range(6))


def hash_code(code: str, salt: str) -> str:
    """SHA-256 hash of (code + salt)."""
    return hashlib.sha256((code + salt).encode()).hexdigest()


def verify_code(code: str, code_hash: str, salt: str) -> bool:
    """Check if the code matches the stored hash."""
    return hash_code(code, salt) == code_hash


async def create_otp(email: str, db: AsyncSession) -> str:
    """Create an OTP row and return the plaintext code."""
    code = generate_code()
    salt = secrets.token_hex(16)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    otp = OtpCode(
        email=email.lower().strip(),
        code_hash=hash_code(code, salt),
        salt=salt,
        expires_at=now + timedelta(minutes=10),
        created_at=now,
    )
    db.add(otp)
    await db.flush()
    return code


async def verify_otp(email: str, code: str, db: AsyncSession) -> bool:
    """Verify an OTP code for the given email.

    Returns True if valid, False otherwise. Increments attempts on each call.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    email = email.lower().strip()

    # Get the latest non-consumed OTP for this email
    otp = (
        await db.execute(
            select(OtpCode)
            .where(
                OtpCode.email == email,
                OtpCode.consumed_at.is_(None),
            )
            .order_by(OtpCode.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if otp is None:
        return False

    # Increment attempts
    otp.attempts += 1

    # Check max attempts
    if otp.attempts > 5:
        return False

    # Check expiry
    if otp.expires_at < now:
        return False

    # Check code
    if not verify_code(code, otp.code_hash, otp.salt):
        return False

    # Success — mark consumed
    otp.consumed_at = now
    await db.flush()
    return True
