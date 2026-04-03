"""
Database engine and session wiring.

Two engines are provided:
  - Async engine  (asyncpg driver)  — used by FastAPI request handlers and the
    SSE event stream via `get_db_session()`.
  - Sync engine   (psycopg2 driver) — used by the background worker and Alembic
    migration scripts that cannot operate in an async context.

Session-scoping rules
---------------------
* Every FastAPI handler receives a *single* session per request via
  `get_db_session()`.  The session is committed on clean exit and rolled back on
  any exception, then closed.  Handlers MUST NOT call `session.commit()` or
  `session.rollback()` directly; raise an exception to trigger rollback.
* The worker uses `get_sync_db_session()`.  Each stage-execution claim is wrapped
  in its own commit so that lease updates are immediately visible to other workers
  (idempotency guard).  Human-review writes use the same scoping — one commit per
  atomic state transition.
* Both engines are constructed once per process (module-level singletons via
  `get_engine()` / `get_sync_engine()`) and cached with `functools.lru_cache`.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Generator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.backend.core.config import get_settings


# ---------------------------------------------------------------------------
# DSN helpers
# ---------------------------------------------------------------------------

def _async_dsn(dsn: str) -> str:
    """Return a DSN that uses the asyncpg driver.

    Replaces ``postgresql://`` or ``postgresql+psycopg2://`` (and similar
    variants) with ``postgresql+asyncpg://``.
    """
    return re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", dsn)


def _sync_dsn(dsn: str) -> str:
    """Return a DSN that uses the psycopg2 driver."""
    return re.sub(r"^postgresql(\+\w+)?://", "postgresql+psycopg2://", dsn)


# ---------------------------------------------------------------------------
# Async engine (API handlers + SSE stream)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return the process-level async SQLAlchemy engine (asyncpg)."""
    settings = get_settings()
    return create_async_engine(
        _async_dsn(settings.postgres_dsn),
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=False,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-level async session factory."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a transactional async session.

    The session is committed when the handler returns normally, and rolled back
    on any unhandled exception.  Do not commit or rollback inside handlers.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Convenience type alias for use in handler signatures:
#   async def my_route(db: DbSession): ...
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


# ---------------------------------------------------------------------------
# Sync engine (worker + Alembic)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_sync_engine() -> Engine:
    """Return the process-level sync SQLAlchemy engine (psycopg2).

    Used by the background worker and Alembic migration scripts.
    """
    settings = get_settings()
    return create_engine(
        _sync_dsn(settings.postgres_dsn),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=False,
    )


@lru_cache(maxsize=1)
def get_sync_session_factory() -> sessionmaker[Session]:
    """Return the process-level sync session factory."""
    return sessionmaker(
        bind=get_sync_engine(),
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


def get_sync_db_session() -> Generator[Session, None, None]:
    """Context-manager-style sync session for the worker.

    Each caller is responsible for committing explicitly after each atomic
    state transition (stage lease claim, stage completion, human-review write).
    The session is always closed on exit and rolled back on unhandled exceptions.

    Usage::

        with get_sync_db_session() as session:
            # claim stage
            session.add(record)
            session.commit()   # immediately visible to other workers
    """
    factory = get_sync_session_factory()
    session: Session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
