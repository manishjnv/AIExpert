"""
Async SQLAlchemy engine, session factory, and FastAPI dependency.

SQLite-specific pragmas (WAL mode, foreign keys) are set on every
connection via an event listener. See DATA_MODEL.md § SQLite-specific notes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def _build_engine(url: str | None = None):
    """Create the async engine with SQLite pragmas.

    Args:
        url: Override database URL (useful for tests). Defaults to settings.
    """
    db_url = url or get_settings().database_url

    # For in-memory SQLite (tests), use StaticPool so all async tasks
    # share the same underlying connection.
    connect_args: dict = {}
    pool_class = None
    if ":memory:" in db_url:
        connect_args["check_same_thread"] = False
        pool_class = StaticPool

    kwargs: dict = {
        "echo": False,
        "connect_args": connect_args,
    }
    if pool_class is not None:
        kwargs["poolclass"] = pool_class

    engine = create_async_engine(db_url, **kwargs)

    # Set WAL mode and enable foreign keys on every raw DBAPI connection.
    # busy_timeout waits up to 30s on lock contention instead of failing — the
    # cron container and live backend can otherwise race on WAL writes and
    # surface "unable to open database file" during aiosqlite connection open.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


# Module-level engine and session factory — initialised lazily in init_db().
engine = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(url: str | None = None) -> None:
    """Initialise the global engine and session factory.

    Called once during the FastAPI lifespan startup. Pass *url* to
    override the database URL (e.g. in tests).
    """
    global engine, async_session_factory
    engine = _build_engine(url)
    async_session_factory = async_sessionmaker(
        engine, expire_on_commit=False,
    )


async def close_db() -> None:
    """Dispose of the engine connection pool. Called on shutdown."""
    global engine, async_session_factory
    if engine is not None:
        await engine.dispose()
        engine = None
        async_session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async session and commits/rollbacks."""
    assert async_session_factory is not None, "Database not initialised — call init_db() first"
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
