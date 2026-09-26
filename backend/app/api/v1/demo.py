"""Demo Data API Router.

Module 46: Demo Data and Example Scenarios.

Exposes endpoints for loading, resetting, and inspecting demo scenarios in development
and testing environments. Strictly forbidden in production.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_db
from app.demo.loader import DemoDataLoader
from app.demo.scenarios import DEMO_USER_EMAIL, DEMO_USER_PASSWORD
from app.dependencies.auth import get_optional_current_user

logger = logging.getLogger("lifethread.api.v1.demo")

router = APIRouter(prefix="/demo", tags=["Demo & Development Scenarios"])


class DemoLoadRequest(BaseModel):
    """Payload for loading demo scenarios."""

    reset_existing: bool = Field(
        default=True,
        description="Whether to clear existing demo data before loading fresh scenarios",
    )
    load_for_current_user: bool = Field(
        default=False,
        description="If True, loads scenarios under the authenticated user instead of default demo user",
    )


class DemoLoadResponse(BaseModel):
    """Result of loading demo scenarios."""

    success: bool
    user_id: str
    user_email: str
    goals_created: int
    tasks_created: int
    dependencies_created: int
    plans_created: int
    memories_created: int
    scenarios: list[dict[str, Any]]
    demo_credentials: dict[str, str] = Field(
        default_factory=lambda: {
            "email": DEMO_USER_EMAIL,
            "password": DEMO_USER_PASSWORD,
        }
    )


class DemoResetResponse(BaseModel):
    """Result of resetting demo scenarios."""

    success: bool
    goals_deleted: int
    memories_deleted: int


class DemoStatusResponse(BaseModel):
    """Current state of demo dataset in database."""

    is_loaded: bool
    user_exists: bool
    user_id: str | None = None
    goals_count: int
    memories_count: int
    environment_allowed: bool


def _verify_demo_access() -> None:
    """Ensure demo data operations are permitted."""
    if not DemoDataLoader.is_demo_allowed():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo data operations are strictly disabled in production environments.",
        )


@router.post(
    "/load",
    response_model=DemoLoadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Load Realistic Demo Scenarios",
    description=(
        "Populates a fresh development or test environment with 6 realistic long-running scenarios: "
        "changing deadlines, limited available time, task failure & recovery, newly discovered weakness, "
        "blocked dependency, and successful completion. Disabled in production."
    ),
)
async def load_demo_data(
    payload: DemoLoadRequest | None = None,
    current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> DemoLoadResponse:
    """Load development scenarios into database."""
    _verify_demo_access()

    req = payload or DemoLoadRequest()
    target_user = current_user if req.load_for_current_user else None

    try:
        result = await DemoDataLoader.load_demo_scenarios(
            session=db,
            target_user=target_user,
            reset_existing=req.reset_existing,
        )
        return DemoLoadResponse(**result)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to load demo data: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to seed demo data: {exc}",
        ) from exc


@router.post(
    "/reset",
    response_model=DemoResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset / Clear Demo Scenarios",
    description="Safely removes demo goals, tasks, plans, and memories without modifying real user data.",
)
async def reset_demo_data(
    current_user: Annotated[User | None, Depends(get_optional_current_user)] = None,
    for_current_user: Annotated[bool, Query(description="Clear for current user if True")] = False,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> DemoResetResponse:
    """Reset demo data."""
    _verify_demo_access()

    target_user_id = current_user.id if (for_current_user and current_user) else None

    try:
        deleted = await DemoDataLoader.clear_demo_data(session=db, target_user_id=target_user_id)
        return DemoResetResponse(success=True, **deleted)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get(
    "/status",
    response_model=DemoStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Inspect Demo Dataset Status",
    description="Returns whether the demo dataset is loaded and counts of goals and memories.",
)
async def get_demo_status(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DemoStatusResponse:
    """Get status of demo dataset."""
    allowed = DemoDataLoader.is_demo_allowed()
    status_data = await DemoDataLoader.get_demo_status(session=db)
    return DemoStatusResponse(environment_allowed=allowed, **status_data)
