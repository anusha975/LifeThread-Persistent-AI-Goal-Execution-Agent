"""REST API endpoints for Module 24 Human-in-the-Loop Permission System."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.db.models.user import User
from app.dependencies.auth import get_current_active_user
from app.services.permissions import (
    ActionPolicy,
    Approval,
    InvalidApprovalError,
    MissingPermissionInfoError,
    PermissionDeniedError,
    PermissionEvaluationResult,
    PermissionRequest,
    Rejection,
    RequestNotFoundError,
    permission_engine,
)

router = APIRouter(prefix="/permissions", tags=["Human-in-the-Loop Permissions"])


class ActionEvaluationRequest(BaseModel):
    action: str = Field(description="Action name or identifier to evaluate")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Action arguments")
    confirmation_override: bool | None = Field(
        default=None,
        description="Optional override for medium-risk confirmation",
    )


class CreatePermissionRequestInput(BaseModel):
    action: str = Field(description="Action requiring approval")
    reason: str = Field(description="Agent's rationale for requesting this action")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    context: dict[str, Any] = Field(default_factory=dict, description="Contextual metadata")
    expires_in_seconds: float | None = Field(
        default=3600.0,
        description="Duration until request expires",
    )


class ApprovalDecisionInput(BaseModel):
    reason: str = Field(default="Approved by user", description="Reason for granting approval")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional audit metadata")


class RejectionDecisionInput(BaseModel):
    reason: str = Field(default="Rejected by user", description="Reason for rejecting the action")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional audit metadata")


class MediumConfirmationSettingInput(BaseModel):
    require_confirmation: bool = Field(
        description="Whether medium risk actions require user confirmation"
    )


# =============================================================================
# POLICIES
# =============================================================================


@router.get(
    "/policies",
    response_model=list[ActionPolicy],
    summary="List all registered action permission policies",
)
async def list_policies(
    _: Annotated[User, Depends(get_current_active_user)],
) -> list[ActionPolicy]:
    """Return all active action risk policies."""
    return permission_engine.registry.list_policies()


@router.post(
    "/policies",
    response_model=ActionPolicy,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new action permission policy",
)
async def register_policy(
    policy: ActionPolicy,
    _: Annotated[User, Depends(get_current_active_user)],
) -> ActionPolicy:
    """Register or update an action risk policy."""
    permission_engine.registry.register_policy(policy)
    return policy


# =============================================================================
# EVALUATION (FAIL-CLOSED)
# =============================================================================


@router.post(
    "/evaluate",
    response_model=PermissionEvaluationResult,
    summary="Evaluate an action against permission policies",
)
async def evaluate_action(
    req: ActionEvaluationRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> PermissionEvaluationResult:
    """Evaluate whether an action is LOW_RISK, MEDIUM_RISK, or HIGH_RISK and if approval is required.

    Fails closed when permission information is missing.
    """
    return permission_engine.evaluate_action(
        user=str(current_user.id),
        action=req.action,
        parameters=req.parameters,
        confirmation_override=req.confirmation_override,
    )


# =============================================================================
# PERMISSION REQUESTS & APPROVAL LIFECYCLE
# =============================================================================


@router.post(
    "/requests",
    response_model=PermissionRequest,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new permission request requiring human authorization",
)
async def create_request(
    body: CreatePermissionRequestInput,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> PermissionRequest:
    """Create a pending permission request when an action requires explicit human approval."""
    try:
        return permission_engine.create_permission_request(
            user=str(current_user.id),
            action=body.action,
            reason=body.reason,
            parameters=body.parameters,
            context=body.context,
            expires_in_seconds=body.expires_in_seconds,
        )
    except MissingPermissionInfoError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get(
    "/requests/pending",
    response_model=list[PermissionRequest],
    summary="List pending permission requests for the authenticated user",
)
async def list_pending_requests(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[PermissionRequest]:
    """Retrieve all pending, non-expired permission requests awaiting user decision."""
    return permission_engine.list_pending_requests(user=str(current_user.id))


@router.post(
    "/requests/{request_id}/approve",
    response_model=Approval,
    summary="Approve a pending permission request",
)
async def approve_request(
    request_id: str,
    body: ApprovalDecisionInput,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Approval:
    """Authorize an action. Records: user, action, reason, timestamp, decision."""
    try:
        return permission_engine.approve_request(
            request_id=request_id,
            user=str(current_user.id),
            reason=body.reason,
            metadata=body.metadata,
        )
    except RequestNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PermissionRequest '{request_id}' not found",
        ) from e
    except PermissionDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except (InvalidApprovalError, MissingPermissionInfoError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post(
    "/requests/{request_id}/reject",
    response_model=Rejection,
    summary="Reject a pending permission request",
)
async def reject_request(
    request_id: str,
    body: RejectionDecisionInput,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Rejection:
    """Deny an action request. Records: user, action, reason, timestamp, decision."""
    try:
        return permission_engine.reject_request(
            request_id=request_id,
            user=str(current_user.id),
            reason=body.reason,
            metadata=body.metadata,
        )
    except RequestNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PermissionRequest '{request_id}' not found",
        ) from e
    except PermissionDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except (InvalidApprovalError, MissingPermissionInfoError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get(
    "/approvals",
    response_model=list[Approval],
    summary="List approval history for the authenticated user",
)
async def list_approvals(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[Approval]:
    """Retrieve all approval records associated with the user."""
    return permission_engine.list_approvals(user=str(current_user.id))


@router.post(
    "/config/medium-confirmation",
    summary="Configure confirmation requirement for medium-risk actions",
)
async def set_medium_confirmation(
    body: MediumConfirmationSettingInput,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Update user preference for whether MEDIUM_RISK actions require confirmation."""
    permission_engine.set_user_medium_confirmation(
        user=str(current_user.id),
        require_confirmation=body.require_confirmation,
    )
    return {
        "status": "UPDATED",
        "user_id": str(current_user.id),
        "require_confirmation_for_medium": body.require_confirmation,
    }
