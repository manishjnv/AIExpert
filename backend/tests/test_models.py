"""Integration tests for ORM models (Task 2.2).

AC: Base.metadata.create_all creates all tables without errors on an empty SQLite file.
"""

import pytest
from sqlalchemy import inspect, text

from app.db import Base, close_db, init_db
import app.db as db_module

# Import all models so they register with Base.metadata
import app.models  # noqa: F401

EXPECTED_TABLES = {
    "users",
    "otp_codes",
    "sessions",
    "user_plans",
    "progress",
    "repo_links",
    "evaluations",
    "plan_versions",
    "curriculum_proposals",
    "link_health",
}


@pytest.mark.asyncio
async def test_create_all_tables():
    """All tables from DATA_MODEL.md are created without errors."""
    await init_db(url="sqlite+aiosqlite:///:memory:")

    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db_module.engine.connect() as conn:
        table_names = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )

    assert EXPECTED_TABLES.issubset(table_names), (
        f"Missing tables: {EXPECTED_TABLES - table_names}"
    )

    await close_db()


@pytest.mark.asyncio
async def test_foreign_keys_enforced():
    """FK constraints are active — inserting a session with a bogus user_id fails."""
    await init_db(url="sqlite+aiosqlite:///:memory:")

    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.models import Session as SessionModel
    from datetime import datetime, timezone

    async with db_module.async_session_factory() as session:
        session.add(SessionModel(
            jti="test-jti",
            user_id=9999,  # no such user
            issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
        ))
        with pytest.raises(Exception):
            await session.commit()

    await close_db()
