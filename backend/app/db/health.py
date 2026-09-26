import asyncio
import logging
import time

from pydantic import BaseModel, Field
from sqlalchemy import text

from app.db.session import get_engine

logger = logging.getLogger("lifethread.db.health")


class DatabaseHealth(BaseModel):
    """Structured database connectivity health response."""

    status: str = Field(..., description="Operational status: 'healthy' or 'unhealthy'")
    latency_ms: float | None = Field(
        default=None, description="Round-trip query latency in milliseconds"
    )
    error: str | None = Field(default=None, description="Error message if unhealthy")


async def check_database_health(timeout_seconds: float = 3.0) -> DatabaseHealth:
    """Execute an async ping ('SELECT 1') against PostgreSQL with latency measurement."""
    engine = get_engine()
    start_time = time.perf_counter()

    try:
        async with asyncio.timeout(timeout_seconds):
            async with engine.connect() as connection:
                result = await connection.execute(text("SELECT 1"))
                row = result.scalar()
                if row != 1:
                    return DatabaseHealth(
                        status="unhealthy",
                        error=f"Unexpected query result from database: {row}",
                    )

        latency_ms = (time.perf_counter() - start_time) * 1000
        return DatabaseHealth(
            status="healthy",
            latency_ms=round(latency_ms, 2),
        )
    except TimeoutError:
        logger.warning("Database health check timed out after %ss", timeout_seconds)
        return DatabaseHealth(
            status="unhealthy",
            error=f"Connection timed out after {timeout_seconds}s",
        )
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        return DatabaseHealth(
            status="unhealthy",
            error=str(exc),
        )
