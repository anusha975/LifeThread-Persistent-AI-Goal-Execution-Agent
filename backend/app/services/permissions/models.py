"""Permission system data models and schemas for Module 24 (Human-in-the-Loop).

Defines:
- RiskLevel: LOW_RISK, MEDIUM_RISK, HIGH_RISK
- ActionPolicy: Risk categorization and confirmation configuration
- PermissionRequest: Pending human-in-the-loop authorization request
- Approval: Explicit or auto-approval audit record
- Rejection: Explicit rejection audit record
- PermissionEvaluationResult: Evaluation outcome before action execution
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(StrEnum):
    """Categorical risk classification for agent actions and tool invocations."""

    LOW_RISK = "LOW_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    HIGH_RISK = "HIGH_RISK"


class RequestStatus(StrEnum):
    """Lifecycle status of a permission request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AUTO_APPROVED = "AUTO_APPROVED"
    EXPIRED = "EXPIRED"


class DecisionType(StrEnum):
    """Outcomes recorded in approval and rejection records."""

    APPROVED = "APPROVED"
    AUTO_APPROVED = "AUTO_APPROVED"
    REJECTED = "REJECTED"


class ActionPolicy(BaseModel):
    """Policy mapping actions to risk levels and confirmation requirements."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_pattern: str = Field(
        ...,
        description="Exact action name or fnmatch pattern (e.g. 'goal:delete', 'email:*', 'mcp:fs:*')",
    )
    risk_level: RiskLevel = Field(
        ...,
        description="LOW_RISK, MEDIUM_RISK, or HIGH_RISK",
    )
    description: str = Field(
        default="",
        description="Human-readable description of why this risk level was assigned",
    )
    require_confirmation_for_medium: bool = Field(
        default=True,
        description="When risk_level is MEDIUM_RISK, whether explicit user confirmation is required",
    )
    allow_auto_approval_for_low: bool = Field(
        default=True,
        description="When risk_level is LOW_RISK, whether it may execute automatically",
    )
    parameter_constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional constraints on action arguments (e.g. max_amount, restricted_targets)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Custom metadata or tagging",
    )


class Approval(BaseModel):
    """Audit record created when an action is authorized.

    Requirement: Every approval must record:
    - user
    - action
    - reason
    - timestamp
    - decision
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user: str = Field(..., description="User identifier who authorized or owns the action")
    action: str = Field(..., description="Action name that was approved")
    reason: str = Field(
        ..., description="Reason for granting approval or system auto-approval reason"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when the approval was granted",
    )
    decision: str = Field(
        default=DecisionType.APPROVED.value,
        description="Decision outcome (e.g. 'APPROVED' or 'AUTO_APPROVED')",
    )
    request_id: str | None = Field(
        default=None,
        description="Associated PermissionRequest ID if originated from a formal request",
    )
    is_explicit: bool = Field(
        default=True,
        description="True if authorized by explicit human decision, False if system auto-approved",
    )
    consumed: bool = Field(
        default=False,
        description="Whether this approval record has been consumed by an execution",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context such as correlation_id, tool parameters, or client IP",
    )


class Rejection(BaseModel):
    """Audit record created when an action authorization request is denied."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user: str = Field(..., description="User identifier who denied or owns the action")
    action: str = Field(..., description="Action name that was rejected")
    reason: str = Field(..., description="Reason for rejecting the action")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when the rejection occurred",
    )
    decision: str = Field(
        default=DecisionType.REJECTED.value,
        description="Decision outcome ('REJECTED')",
    )
    request_id: str | None = Field(
        default=None,
        description="Associated PermissionRequest ID",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional audit metadata",
    )


class PermissionRequest(BaseModel):
    """Formal request created when an action requires human authorization."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = Field(..., description="User from whom permission is requested")
    action: str = Field(..., description="Action name requiring permission")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters or arguments the agent intends to supply",
    )
    risk_level: RiskLevel = Field(..., description="Evaluated risk level")
    reason: str = Field(
        ...,
        description="Agent's rationale explaining why this action is necessary",
    )
    status: RequestStatus = Field(
        default=RequestStatus.PENDING,
        description="Current lifecycle status of the request",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Contextual metadata (goal_id, task_id, correlation_id)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Creation timestamp",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiration timestamp after which the request becomes invalid",
    )
    approval_id: str | None = Field(
        default=None,
        description="ID of the Approval record if approved",
    )
    rejection_id: str | None = Field(
        default=None,
        description="ID of the Rejection record if rejected",
    )


class PermissionEvaluationResult(BaseModel):
    """Result of evaluating an action against configured policies before execution."""

    model_config = ConfigDict(extra="ignore")

    action: str
    risk_level: RiskLevel
    requires_approval: bool
    can_execute_immediately: bool
    policy_matched: ActionPolicy | None = None
    reason: str
    fail_closed: bool = False
