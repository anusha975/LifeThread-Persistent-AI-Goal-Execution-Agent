import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger("lifethread.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return or initialize the async SQLAlchemy engine with connection pooling."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.DB_ECHO or settings.DEBUG,
            future=True,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=settings.DB_POOL_PRE_PING,
        )
        logger.info(
            "Initialized async database engine",
            extra={
                "pool_size": settings.DB_POOL_SIZE,
                "max_overflow": settings.DB_MAX_OVERFLOW,
                "pool_pre_ping": settings.DB_POOL_PRE_PING,
            },
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return or initialize the session maker."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_factory


async def close_db_engine() -> None:
    """Dispose the database engine and close all pooled connections."""
    global _engine, _session_factory
    if _engine is not None:
        logger.info("Disposing async database engine")
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for providing an async database session per request.

    Features automatic transaction handling:
    - Commits if the request executes without exception.
    - Rolls back if an unhandled exception is raised.
    - Guarantees session closure.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def transaction_context() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for standalone atomic transactions.

    Usage:
        async with transaction_context() as session:
            session.add(model)
            # automatically committed on exit, or rolled back on error
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
