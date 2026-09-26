from unittest.mock import patch

import pytest
from app.db.health import check_database_health
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_database_health_success() -> None:
    """Verify check_database_health reports healthy and calculates latency."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    with patch("app.db.health.get_engine", return_value=test_engine):
        health = await check_database_health(timeout_seconds=2.0)

        assert health.status == "healthy"
        assert health.latency_ms is not None
        assert health.latency_ms >= 0.0
        assert health.error is None

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_database_health_failure() -> None:
    """Verify check_database_health handles connection failure gracefully."""
    # Point engine to non-existent unreachable database socket
    bad_engine = create_async_engine("sqlite+aiosqlite:///non_existent_dir/unreachable.db")

    with patch("app.db.health.get_engine", return_value=bad_engine):
        health = await check_database_health(timeout_seconds=1.0)

        assert health.status == "unhealthy"
        assert health.latency_ms is None
        assert health.error is not None

    await bad_engine.dispose()


@pytest.mark.asyncio
async def test_database_health_timeout() -> None:
    """Verify check_database_health handles timeout gracefully."""

    class HangingEngine:
        def connect(self):
            class HangingCM:
                async def __aenter__(self):
                    import asyncio

                    await asyncio.sleep(2.0)

                async def __aexit__(self, exc_type, exc, tb):
                    pass

            return HangingCM()

    with patch("app.db.health.get_engine", return_value=HangingEngine()):
        health = await check_database_health(timeout_seconds=0.1)

        assert health.status == "unhealthy"
        assert "timed out" in (health.error or "").lower()
