"""Database ORM models for Module 24 Human-in-the-Loop Permission System."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.models.base import BaseDBModel

if TYPE_CHECKING:
    from app.db.models.user import User


class PermissionRequestModel(BaseDBModel):
    """Database model for formal human-in-the-loop authorization requests."""

    __tablename__ = "permission_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="User from whom permission is requested",
    )
    action: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Action name requiring permission",
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Parameters or arguments the agent intends to supply",
    )
    risk_level: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Evaluated risk level: LOW_RISK, MEDIUM_RISK, HIGH_RISK",
    )
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Agent's rationale explaining why this action is required",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PENDING",
        index=True,
        doc="Current status: PENDING, APPROVED, REJECTED, EXPIRED, AUTO_APPROVED",
    )
    context_data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Contextual metadata (goal_id, task_id, correlation_id)",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Optional expiration timestamp",
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        lazy="joined",
    )
    approvals: Mapped[list["ApprovalModel"]] = relationship(
        "ApprovalModel",
        back_populates="request",
        cascade="all, delete-orphan",
    )
    rejections: Mapped[list["RejectionModel"]] = relationship(
        "RejectionModel",
        back_populates="request",
        cascade="all, delete-orphan",
    )


class ApprovalModel(BaseDBModel):
    """Database model for action approvals.

    Requirement: Every approval must record:
    - user
    - action
    - reason
    - timestamp
    - decision
    """

    __tablename__ = "permission_approvals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="User who authorized or owns the action",
    )
    action: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Action name that was approved",
    )
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Reason for granting approval",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        doc="UTC timestamp when approval was granted",
    )
    decision: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="APPROVED",
        doc="Decision record: APPROVED or AUTO_APPROVED",
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("permission_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Optional link to PermissionRequestModel",
    )
    is_explicit: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="True if human approved, False if system auto-approved",
    )
    consumed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether this approval has already been used by an execution",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Additional audit context",
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        lazy="joined",
    )
    request: Mapped[PermissionRequestModel | None] = relationship(
        "PermissionRequestModel",
        back_populates="approvals",
    )


class RejectionModel(BaseDBModel):
    """Database model for action rejections."""

    __tablename__ = "permission_rejections"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="User who denied or owns the action",
    )
    action: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Action name that was rejected",
    )
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Reason for rejecting the action",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        doc="UTC timestamp when rejection occurred",
    )
    decision: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="REJECTED",
        doc="Decision record: REJECTED",
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("permission_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Optional link to PermissionRequestModel",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Additional audit context",
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        lazy="joined",
    )
    request: Mapped[PermissionRequestModel | None] = relationship(
        "PermissionRequestModel",
        back_populates="rejections",
    )


class ActionPolicyModel(BaseDBModel):
    """Database model for persistent Action Policies."""

    __tablename__ = "action_policies"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="Optional user-specific policy. Null for global system policies.",
    )
    action_pattern: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Action pattern matching key or wildcard",
    )
    risk_level: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="LOW_RISK, MEDIUM_RISK, HIGH_RISK",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Rationale for the assigned risk level",
    )
    require_confirmation_for_medium: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether medium risk actions require user confirmation",
    )
    allow_auto_approval_for_low: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether low risk actions may execute automatically",
    )
    parameter_constraints: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Constraints on action parameters",
    )
