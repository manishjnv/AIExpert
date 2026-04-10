"""Shared test fixtures for backend tests."""

import pytest_asyncio  # noqa: F401 (available inside container)

from app.db import Base, async_session_factory, close_db, engine, init_db


@pytest_asyncio.fixture
async def db_session():
    """Provide an async session backed by an in-memory SQLite database.

    Creates all tables before the test and tears everything down after.
    """
    await init_db(url="sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        yield session

    await close_db()
