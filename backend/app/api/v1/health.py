from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.config import Settings
from app.db.health import check_database_health
from app.dependencies.common import get_app_settings
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter()

SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness Probe",
    description="Returns basic operational liveness status of the API service.",
)
async def check_health(settings: SettingsDep) -> HealthResponse:
    """Liveness probe verifying that the API process is alive and responding."""
    return HealthResponse(
        status="ok",
        service="lifethread-api",
        version=settings.VERSION,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness Probe",
    description="Returns operational readiness and dependency status checks.",
)
async def check_readiness(settings: SettingsDep) -> ReadinessResponse:
    """Readiness probe verifying that the API is ready to accept user traffic."""
    db_health = await check_database_health()

    return ReadinessResponse(
        status="ready" if db_health.status in ["healthy", "configured"] else "degraded",
        service="lifethread-api",
        version=settings.VERSION,
        checks={
            "database": db_health.status,
            "redis": "configured",
        },
    )
