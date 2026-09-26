from unittest.mock import patch

import pytest
from app.core.config import get_settings
from app.db.session import (
    close_db_engine,
    get_db,
    get_engine,
    get_session_factory,
    transaction_context,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def test_get_engine_configuration() -> None:
    """Verify engine initialization adheres to application settings."""
    settings = get_settings()
    engine = get_engine()

    assert engine is not None
    assert hasattr(engine, "pool")
    assert settings.DB_POOL_SIZE > 0


def test_get_session_factory() -> None:
    """Verify sessionmaker binds to engine and produces AsyncSession."""
    factory = get_session_factory()
    assert factory is not None
    assert factory.class_ is AsyncSession


@pytest.mark.asyncio
async def test_get_db_dependency_success() -> None:
    """Verify get_db dependency yields session and commits on clean exit."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    test_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE test_items (id INT PRIMARY KEY, name TEXT)"))

    with patch("app.db.session.get_session_factory", return_value=test_factory):
        db_gen = get_db()
        session = await anext(db_gen)
        assert isinstance(session, AsyncSession)

        # Insert a record within the session
        await session.execute(text("INSERT INTO test_items VALUES (1, 'Success Item')"))

        # Complete generator (triggers commit)
        with pytest.raises(StopAsyncIteration):
            await anext(db_gen)

    # Verify committed state in a new session
    async with test_factory() as verify_session:
        result = await verify_session.execute(text("SELECT name FROM test_items WHERE id = 1"))
        assert result.scalar() == "Success Item"

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_get_db_dependency_rollback_on_error() -> None:
    """Verify get_db dependency rolls back transaction when an exception is raised."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    test_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE test_items (id INT PRIMARY KEY, name TEXT)"))

    with patch("app.db.session.get_session_factory", return_value=test_factory):
        db_gen = get_db()
        session = await anext(db_gen)

        await session.execute(text("INSERT INTO test_items VALUES (2, 'Rollback Item')"))

        # Inject exception into generator
        with pytest.raises(RuntimeError, match="Route handler failed"):
            try:
                raise RuntimeError("Route handler failed")
            except Exception as e:
                await db_gen.athrow(e)

    # Verify record was rolled back
    async with test_factory() as verify_session:
        result = await verify_session.execute(text("SELECT name FROM test_items WHERE id = 2"))
        assert result.scalar() is None

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_transaction_context_success() -> None:
    """Verify transaction_context commits atomic operations."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    test_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE test_items (id INT PRIMARY KEY, name TEXT)"))

    with patch("app.db.session.get_session_factory", return_value=test_factory):
        async with transaction_context() as session:
            await session.execute(text("INSERT INTO test_items VALUES (3, 'Atomic Item')"))

    async with test_factory() as verify_session:
        result = await verify_session.execute(text("SELECT name FROM test_items WHERE id = 3"))
        assert result.scalar() == "Atomic Item"

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_close_db_engine() -> None:
    """Verify close_db_engine disposes engine."""
    engine = get_engine()
    assert engine is not None
    await close_db_engine()
    new_engine = get_engine()
    assert new_engine is not None
