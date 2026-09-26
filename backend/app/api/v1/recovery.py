from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.db.models.user import User
from app.dependencies.auth import get_current_active_user
from app.services.recovery import (
    FailureRecoveryEngine,
    UserNotification,
    idempotency_manager,
)

router = APIRouter(prefix="/recovery", tags=["Failure Recovery"])


class IdempotencyCheckRequest(BaseModel):
    key: str = Field(description="Idempotency key to check")


class IdempotencyCheckResponse(BaseModel):
    key: str
    is_completed: bool
    execution_count: int


@router.get(
    "/notifications",
    response_model=list[UserNotification],
    summary="Get active user failure and degradation notifications",
)
async def get_user_notifications(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[UserNotification]:
    """Retrieve all active, non-dismissed failure and recovery notifications for the authenticated user."""
    return FailureRecoveryEngine.get_user_notifications(user_id=current_user.id)


@router.post(
    "/notifications/{notification_id}/dismiss",
    summary="Dismiss a recovery notification",
)
async def dismiss_notification(
    notification_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Dismiss a specific user notification."""
    success = FailureRecoveryEngine.dismiss_notification(
        notification_id=notification_id,
        user_id=current_user.id,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found or already dismissed",
        )
    return {"status": "DISMISSED", "notification_id": notification_id}


@router.post(
    "/idempotency/check",
    response_model=IdempotencyCheckResponse,
    summary="Check status of an idempotency key",
)
async def check_idempotency_key(
    request: IdempotencyCheckRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> IdempotencyCheckResponse:
    """Inspect idempotency key execution status."""
    is_comp = idempotency_manager.is_completed(request.key)
    count = idempotency_manager.get_execution_count(request.key)
    return IdempotencyCheckResponse(
        key=request.key,
        is_completed=is_comp,
        execution_count=count,
    )
