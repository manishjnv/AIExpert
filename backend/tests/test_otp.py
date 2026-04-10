"""Tests for OTP generation and verification (Task 3.4).

AC: End-to-end OTP sign-in logic works.
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.auth.otp import create_otp, generate_code, hash_code, verify_code, verify_otp
from app.db import Base, close_db, init_db
import app.db as db_module
from app.models.user import OtpCode

import app.models  # noqa: F401


async def _setup():
    await init_db(url="sqlite+aiosqlite:///:memory:")
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def test_generate_code():
    code = generate_code()
    assert len(code) == 6
    assert code.isdigit()


def test_hash_and_verify():
    code = "123456"
    salt = "deadbeef"
    h = hash_code(code, salt)
    assert verify_code(code, h, salt)
    assert not verify_code("000000", h, salt)


@pytest.mark.asyncio
async def test_create_and_verify_otp():
    await _setup()

    async with db_module.async_session_factory() as db:
        code = await create_otp("test@example.com", db)
        await db.commit()

        assert len(code) == 6
        result = await verify_otp("test@example.com", code, db)
        assert result is True
        await db.commit()

    await close_db()


@pytest.mark.asyncio
async def test_verify_otp_wrong_code():
    await _setup()

    async with db_module.async_session_factory() as db:
        await create_otp("wrong@example.com", db)
        await db.commit()

        result = await verify_otp("wrong@example.com", "000000", db)
        assert result is False

    await close_db()


@pytest.mark.asyncio
async def test_verify_otp_expired():
    await _setup()

    async with db_module.async_session_factory() as db:
        code = await create_otp("expired@example.com", db)
        await db.commit()

        # Manually set expires_at to the past
        from sqlalchemy import select
        otp = (await db.execute(
            select(OtpCode).where(OtpCode.email == "expired@example.com")
        )).scalar_one()
        otp.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        await db.commit()

        result = await verify_otp("expired@example.com", code, db)
        assert result is False

    await close_db()


@pytest.mark.asyncio
async def test_verify_otp_max_attempts():
    await _setup()

    async with db_module.async_session_factory() as db:
        code = await create_otp("attempts@example.com", db)
        await db.commit()

        # Use up 5 wrong attempts
        for _ in range(5):
            await verify_otp("attempts@example.com", "000000", db)
            await db.flush()

        # Now even the correct code should fail
        result = await verify_otp("attempts@example.com", code, db)
        assert result is False

    await close_db()
