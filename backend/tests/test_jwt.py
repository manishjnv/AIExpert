"""Unit tests for JWT helpers (Task 3.1).

AC: Tests cover issue, verify, and revoke.
"""

import pytest
from datetime import datetime, timezone

from jose import jwt as jose_jwt

from app.db import Base, close_db, init_db
import app.db as db_module
from app.auth.jwt import ALGORITHM, issue_token, revoke_session, verify_token
from app.config import get_settings

import app.models  # noqa: F401 — register all models
from app.models.user import User


async def _setup_db():
    """Spin up an in-memory DB with all tables."""
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _create_user(db) -> User:
    user = User(
        email="test@example.com",
        provider="otp",
        is_admin=False,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_issue_and_verify():
    """issue_token returns a JWT that verify_token resolves to the user."""
    await _setup_db()

    async with db_module.async_session_factory() as db:
        user = await _create_user(db)
        token = await issue_token(user, db, user_agent="test-agent", ip="127.0.0.1")
        await db.commit()

        # Verify returns the same user
        resolved = await verify_token(token, db)
        assert resolved is not None
        assert resolved.id == user.id
        assert resolved.email == "test@example.com"

    await close_db()


@pytest.mark.asyncio
async def test_token_payload_structure():
    """Issued JWT contains sub, jti, iat, exp claims."""
    await _setup_db()

    async with db_module.async_session_factory() as db:
        user = await _create_user(db)
        token = await issue_token(user, db)
        await db.commit()

    settings = get_settings()
    payload = jose_jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    assert payload["sub"] == str(user.id)
    assert "jti" in payload
    assert "iat" in payload
    assert "exp" in payload
    # 30-day expiry
    assert payload["exp"] - payload["iat"] == 30 * 86400

    await close_db()


@pytest.mark.asyncio
async def test_revoke_then_verify_fails():
    """After revoking, verify_token returns None."""
    await _setup_db()

    async with db_module.async_session_factory() as db:
        user = await _create_user(db)
        token = await issue_token(user, db)
        await db.commit()

        # Extract jti from token
        settings = get_settings()
        payload = jose_jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        jti = payload["jti"]

        # Revoke
        revoked = await revoke_session(jti, db)
        assert revoked is True
        await db.commit()

        # Verify should now fail
        resolved = await verify_token(token, db)
        assert resolved is None

    await close_db()


@pytest.mark.asyncio
async def test_revoke_nonexistent_returns_false():
    """Revoking a non-existent JTI returns False."""
    await _setup_db()

    async with db_module.async_session_factory() as db:
        result = await revoke_session("no-such-jti", db)
        assert result is False

    await close_db()


@pytest.mark.asyncio
async def test_verify_bad_token_returns_none():
    """A garbage token returns None, not an exception."""
    await _setup_db()

    async with db_module.async_session_factory() as db:
        result = await verify_token("not.a.real.token", db)
        assert result is None

    await close_db()
