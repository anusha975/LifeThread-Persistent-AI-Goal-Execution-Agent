import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.models.base import BaseDBModel
from app.db.models.goal import GoalPriority

if TYPE_CHECKING:
    from app.db.models.goal import Goal
    from app.db.models.task import Task


class PlanStatus(StrEnum):
    """Operational lifecycle statuses for a Plan version."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    INFEASIBLE = "INFEASIBLE"
    CANCELLED = "CANCELLED"


class Plan(BaseDBModel):
    """Versioned execution schedule allocating tasks across time and available capacity."""

    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("goal_id", "version", name="uq_plan_goal_version"),)

    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated goal identifier",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        index=True,
        doc="Monotonically increasing plan version number",
    )
    status: Mapped[PlanStatus] = mapped_column(
        SQLAlchemyEnum(PlanStatus, name="plan_status_enum"),
        default=PlanStatus.ACTIVE,
        nullable=False,
        index=True,
        doc="Plan operational status",
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp of plan generation",
    )
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Trigger rationale or generation explanation",
    )
    is_feasible: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether all tasks fit within deadline and capacity constraints",
    )
    deadline_risk: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        doc="Calculated risk score of exceeding the goal deadline (0.0 to 1.0+)",
    )
    risk_level: Mapped[str] = mapped_column(
        String(20),
        default="LOW",
        nullable=False,
        doc="Categorical deadline risk level: LOW, MEDIUM, HIGH, CRITICAL",
    )
    schedule_utilization: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        doc="Ratio of scheduled task workload to available working capacity",
    )
    total_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Sum of task estimated effort in minutes",
    )
    scheduled_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Earliest scheduled task start in UTC",
    )
    scheduled_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Latest scheduled task finish in UTC",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        nullable=False,
        doc="Scheduling parameters, daily hours, working windows, and infeasibility details",
    )

    # Relationships
    goal: Mapped["Goal"] = relationship("Goal", back_populates="plans")
    items: Mapped[list["PlanItem"]] = relationship(
        "PlanItem",
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PlanItem.scheduled_start",
    )


class PlanItem(BaseDBModel):
    """Scheduled task time slot within a concrete plan."""

    __tablename__ = "plan_items"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Parent plan version identifier",
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Assigned task identifier",
    )
    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Scheduled task start timestamp in UTC",
    )
    scheduled_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Scheduled task completion timestamp in UTC",
    )
    priority: Mapped[GoalPriority] = mapped_column(
        SQLAlchemyEnum(GoalPriority, name="goal_priority_enum"),
        default=GoalPriority.MEDIUM,
        nullable=False,
        doc="Task priority rank for scheduling",
    )
    rationale: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Explicit justification explaining why this task is scheduled at this window",
    )

    # Relationships
    plan: Mapped["Plan"] = relationship("Plan", back_populates="items")
    task: Mapped["Task"] = relationship("Task", back_populates="plan_items")
