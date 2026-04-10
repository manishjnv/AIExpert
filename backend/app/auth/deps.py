"""
FastAPI dependencies for authentication.

- get_current_user: reads the `session` httpOnly cookie, verifies the JWT,
  returns the User or raises 401.
- get_current_admin: same, but also checks is_admin or raises 403.
"""

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import verify_token
from app.db import get_db
from app.models.user import User


async def get_current_user(
    auth_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the current user from the session cookie.

    Raises 401 if the cookie is missing, invalid, expired, or revoked.
    """
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await verify_token(auth_token, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Like get_current_user but also requires is_admin=True."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
