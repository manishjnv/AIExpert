"""
JWT session helpers — issue, verify, and revoke tokens.

Tokens use python-jose with HS256. Each token carries a `jti` (UUID)
that maps to a row in the `sessions` table so we can revoke individual
sessions server-side.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import Session as SessionModel, User

ALGORITHM = "HS256"


async def issue_token(
    user: User,
    db: AsyncSession,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
) -> str:
    """Create a JWT and persist a matching session row.

    Returns the encoded JWT string.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.jwt_expiry_days)
    jti = str(uuid.uuid4())

    payload = {
        "sub": str(user.id),
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)

    session_row = SessionModel(
        jti=jti,
        user_id=user.id,
        issued_at=now,
        expires_at=expires,
        user_agent=user_agent,
        ip=ip,
    )
    db.add(session_row)
    await db.flush()

    return token


async def verify_token(token: str, db: AsyncSession) -> User | None:
    """Decode a JWT and return the associated User if the session is valid.

    Returns None on any failure (expired, revoked, bad signature, etc.).
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        return None

    jti: str | None = payload.get("jti")
    sub: str | None = payload.get("sub")
    if not jti or not sub:
        return None

    session_row = (
        await db.execute(
            select(SessionModel).where(
                SessionModel.jti == jti,
                SessionModel.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if session_row is None:
        return None

    # Check expiry server-side as well (SQLite returns naive datetimes)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if session_row.expires_at < now:
        return None

    user = await db.get(User, int(sub))
    return user


async def revoke_session(jti: str, db: AsyncSession) -> bool:
    """Mark a session as revoked. Returns True if a session was found and revoked."""
    session_row = (
        await db.execute(
            select(SessionModel).where(
                SessionModel.jti == jti,
                SessionModel.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if session_row is None:
        return False

    session_row.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    return True
