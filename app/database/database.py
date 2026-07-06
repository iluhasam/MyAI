"""Async database engine + session management.

Wraps a SQLAlchemy 2.0 async engine and an ``async_sessionmaker``. The
``session()`` context manager yields a session with commit-on-success /
rollback-on-error semantics and guaranteed cleanup — the single source of
transactional truth used by repositories, services and workers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.exceptions import ConfigurationError
from app.core.logger import get_logger
from app.database.models import Base

_log = get_logger(__name__)


class Database:
    """Owns the async engine and hands out transactional sessions."""

    def __init__(self, url: str) -> None:
        if not url:
            raise ConfigurationError("DATABASE_URL is empty")
        self._url = url
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    async def connect(self) -> None:
        """Create the engine/session factory (idempotent). Ensures SQLite dir exists."""
        if self._engine is not None:
            return
        self._ensure_sqlite_path()
        self._engine = create_async_engine(self._url, pool_pre_ping=True, future=True)
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )
        _log.info("database connected", extra={"url": self._safe_url()})

    async def disconnect(self) -> None:
        """Dispose the engine and release all pooled connections."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None
            _log.info("database disconnected")

    async def create_all(self) -> None:
        """Create tables from ORM metadata (MVP convenience; use Alembic in prod)."""
        engine = self._require_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _log.info("schema ensured")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session; commit on success, roll back on any exception."""
        if self._sessionmaker is None:
            raise ConfigurationError("Database.connect() must be called before use")
        session = self._sessionmaker()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Expose the raw factory (used by ARQ workers for scoped sessions)."""
        if self._sessionmaker is None:
            raise ConfigurationError("Database.connect() must be called before use")
        return self._sessionmaker

    # -- internals ----------------------------------------------------------
    def _require_engine(self) -> AsyncEngine:
        if self._engine is None:
            raise ConfigurationError("Database.connect() must be called before use")
        return self._engine

    def _ensure_sqlite_path(self) -> None:
        prefix = "sqlite+aiosqlite:///"
        if self._url.startswith(prefix):
            db_path = self._url[len(prefix):]
            if db_path and db_path != ":memory:":
                Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    def _safe_url(self) -> str:
        """Redact credentials before logging a DSN."""
        if "@" in self._url:
            scheme, _, tail = self._url.partition("://")
            return f"{scheme}://***@{tail.split('@', 1)[-1]}"
        return self._url
