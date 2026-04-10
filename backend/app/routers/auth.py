"""
Auth router — Google OAuth, OTP, /me, /logout.

All endpoints under /api/auth (prefix set in main.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jose import JWTError
from jose import jwt as jose_jwt

from app.auth.deps import get_current_user
from app.auth.google import oauth
from app.auth.jwt import ALGORITHM, issue_token, revoke_session
from app.config import get_settings
from app.db import get_db
from app.models.user import User

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ------------------------------------------------------------------ #
# Google OAuth
# ------------------------------------------------------------------ #

def _require_google():
    """Raise 501 if Google OAuth is not configured."""
    settings = get_settings()
    if not settings.google_client_id or "google" not in oauth._registry:  # noqa: SLF001
        raise HTTPException(status_code=501, detail="Google OAuth not configured")


@router.get("/google/login")
async def google_login(request: Request):
    """Redirect to Google's consent screen."""
    _require_google()
    settings = get_settings()
    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Exchange Google auth code for tokens, upsert user, issue session cookie."""
    _require_google()

    try:
        token_data = await oauth.google.authorize_access_token(request)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Failed to authenticate with Google") from exc

    userinfo = token_data.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=401, detail="Failed to get user info from Google")

    email = userinfo.get("email", "").lower().strip()
    if not email:
        raise HTTPException(status_code=401, detail="No email returned from Google")

    google_sub = userinfo.get("sub")
    name = userinfo.get("name")
    avatar_url = userinfo.get("picture")

    # Upsert user
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if user is None:
        user = User(
            email=email,
            name=name,
            avatar_url=avatar_url,
            provider="google",
            provider_id=google_sub,
        )
        db.add(user)
        await db.flush()
    else:
        # Update fields from Google on each login
        user.name = name or user.name
        user.avatar_url = avatar_url or user.avatar_url
        if google_sub:
            user.provider_id = google_sub

    # Issue JWT
    jwt_token = await issue_token(
        user, db,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    await db.commit()

    # Set httpOnly cookie and redirect to frontend
    settings = get_settings()
    response = Response(status_code=307, headers={"Location": "/"})
    response.set_cookie(
        key="session",
        value=jwt_token,
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",
        max_age=settings.jwt_expiry_days * 86400,
        path="/",
    )
    return response


# ------------------------------------------------------------------ #
# Email OTP (Task 3.4)
# ------------------------------------------------------------------ #

@router.post("/otp/request", status_code=204)
@limiter.limit("5/15minutes")
async def otp_request(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send an OTP code to the provided email. Always returns 204 (no user enumeration)."""
    from pydantic import BaseModel, EmailStr

    class OtpRequestBody(BaseModel):
        email: EmailStr

    body = OtpRequestBody(**(await request.json()))
    email = body.email.lower().strip()

    from app.auth.otp import create_otp
    from app.services.email_sender import send_otp_email

    code = await create_otp(email, db)
    await send_otp_email(email, code)
    return Response(status_code=204)


@router.post("/otp/verify")
@limiter.limit("10/15minutes")
async def otp_verify(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify an OTP code and issue a session cookie on success."""
    from pydantic import BaseModel, EmailStr

    class OtpVerifyBody(BaseModel):
        email: EmailStr
        code: str

    body = OtpVerifyBody(**(await request.json()))
    email = body.email.lower().strip()

    from app.auth.otp import verify_otp

    if not await verify_otp(email, body.code, db):
        raise HTTPException(status_code=401, detail="invalid_or_expired")

    # Upsert user
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if user is None:
        user = User(email=email, provider="otp")
        db.add(user)
        await db.flush()

    jwt_token = await issue_token(
        user, db,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )

    settings = get_settings()
    response = Response(
        content='{"ok":true}',
        media_type="application/json",
    )
    response.set_cookie(
        key="session",
        value=jwt_token,
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",
        max_age=settings.jwt_expiry_days * 86400,
        path="/",
    )
    return response


# ------------------------------------------------------------------ #
# /me and /logout (Task 3.6)
# ------------------------------------------------------------------ #

@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "github_username": user.github_username,
        "learning_goal": user.learning_goal,
        "experience_level": user.experience_level,
        "is_admin": user.is_admin,
    }


@router.post("/logout")
async def logout(
    request: Request,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current session and clear the cookie."""
    settings = get_settings()
    token = request.cookies.get("session")
    if token:
        try:
            payload = jose_jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
            jti = payload.get("jti")
            if jti:
                await revoke_session(jti, db)
        except JWTError:
            pass

    response = Response(status_code=204)
    response.delete_cookie("session", path="/")
    return response
