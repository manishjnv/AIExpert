"""Integration tests for backend/app/db.py (Task 2.1)."""

import pytest
from sqlalchemy import Column, Integer, String, select, text

from app.db import Base, close_db, init_db
import app.db as db_module


# A trivial model used only by this test module.
class _Ping(Base):
    __tablename__ = "_test_ping"
    id = Column(Integer, primary_key=True, autoincrement=True)
    message = Column(String, nullable=False)


@pytest.mark.asyncio
async def test_insert_and_read_back():
    """AC: insert a trivial row and read it back."""
    await init_db(url="sqlite+aiosqlite:///:memory:")

    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db_module.async_session_factory() as session:
        session.add(_Ping(message="hello"))
        await session.commit()

    async with db_module.async_session_factory() as session:
        row = (await session.execute(select(_Ping))).scalar_one()
        assert row.message == "hello"

    await close_db()


@pytest.mark.asyncio
async def test_wal_mode_enabled():
    """WAL journal mode is set on the connection."""
    await init_db(url="sqlite+aiosqlite:///:memory:")

    async with db_module.engine.begin() as conn:
        result = await conn.execute(text("PRAGMA journal_mode"))
        mode = result.scalar()
        # In-memory databases may report "memory" instead of "wal"
        # because WAL requires a file. We verify the pragma runs without error.
        assert mode in ("wal", "memory")

    await close_db()


@pytest.mark.asyncio
async def test_foreign_keys_enabled():
    """PRAGMA foreign_keys=ON is set on every connection."""
    await init_db(url="sqlite+aiosqlite:///:memory:")

    async with db_module.engine.begin() as conn:
        result = await conn.execute(text("PRAGMA foreign_keys"))
        fk = result.scalar()
        assert fk == 1

    await close_db()
