"""Module 24: Human-in-the-Loop Permission System."""

from app.services.permissions.engine import PermissionEngine, permission_engine
from app.services.permissions.exceptions import (
    InvalidApprovalError,
    MissingPermissionInfoError,
    PermissionDeniedError,
    PermissionRequiredError,
    PermissionSystemError,
    RequestNotFoundError,
)
from app.services.permissions.models import (
    ActionPolicy,
    Approval,
    DecisionType,
    PermissionEvaluationResult,
    PermissionRequest,
    Rejection,
    RequestStatus,
    RiskLevel,
)
from app.services.permissions.policy_registry import DEFAULT_SYSTEM_POLICIES, PolicyRegistry

__all__ = [
    "DEFAULT_SYSTEM_POLICIES",
    "ActionPolicy",
    "Approval",
    "DecisionType",
    "InvalidApprovalError",
    "MissingPermissionInfoError",
    "PermissionDeniedError",
    "PermissionEngine",
    "PermissionEvaluationResult",
    "PermissionRequest",
    "PermissionRequiredError",
    "PermissionSystemError",
    "PolicyRegistry",
    "Rejection",
    "RequestNotFoundError",
    "RequestStatus",
    "RiskLevel",
    "permission_engine",
]
