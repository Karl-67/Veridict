from __future__ import annotations

from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from app.backend.core.config import get_settings

_async_engine = None
_async_session_factory = None
_sync_engine = None
_sync_session_factory = None


def get_engine():
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        dsn = settings.postgres_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        _async_engine = create_async_engine(dsn, pool_pre_ping=True)
    return _async_engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False
        )
    return _async_session_factory


def get_sync_session_factory():
    global _sync_engine, _sync_session_factory
    if _sync_session_factory is None:
        settings = get_settings()
        _sync_engine = create_engine(settings.postgres_dsn, pool_pre_ping=True)
        _sync_session_factory = sessionmaker(bind=_sync_engine)
    return _sync_session_factory


async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(_get_db)]
