import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.models.base import BaseDBModel

if TYPE_CHECKING:
    from app.db.models.plan import Plan
    from app.db.models.task import GoalDecomposition, Task
    from app.db.models.user import User


class GoalStatus(StrEnum):
    """Lifecycle statuses for a Goal."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"


class GoalPriority(StrEnum):
    """Execution priority levels for a Goal."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MilestoneStatus(StrEnum):
    """Execution statuses for a Goal Milestone."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


class Goal(BaseDBModel):
    """Central domain entity representing a persistent long-running goal."""

    __tablename__ = "goals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner user identifier",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Meaningful title of the goal",
    )
    objective: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="High-level target objective or mission statement",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Detailed background, motivation, or guidance",
    )
    status: Mapped[GoalStatus] = mapped_column(
        SQLAlchemyEnum(GoalStatus, name="goal_status_enum"),
        default=GoalStatus.ACTIVE,
        nullable=False,
        index=True,
        doc="Current lifecycle state",
    )
    priority: Mapped[GoalPriority] = mapped_column(
        SQLAlchemyEnum(GoalPriority, name="goal_priority_enum"),
        default=GoalPriority.MEDIUM,
        nullable=False,
        index=True,
        doc="Goal priority rank",
    )
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Optional target completion deadline in UTC",
    )
    success_criteria: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        doc="List of measurable acceptance criteria required to achieve the goal",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="goals")
    constraints: Mapped[list["GoalConstraint"]] = relationship(
        "GoalConstraint",
        back_populates="goal",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    milestones: Mapped[list["GoalMilestone"]] = relationship(
        "GoalMilestone",
        back_populates="goal",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="GoalMilestone.order_index",
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="goal",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    decompositions: Mapped[list["GoalDecomposition"]] = relationship(
        "GoalDecomposition",
        back_populates="goal",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="GoalDecomposition.version",
    )
    plans: Mapped[list["Plan"]] = relationship(
        "Plan",
        back_populates="goal",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Plan.version",
    )


class GoalConstraint(BaseDBModel):
    """Guiding constraint or limitation placed upon a goal's execution."""

    __tablename__ = "goal_constraints"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated goal identifier",
    )
    type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Classification of constraint (e.g. budget, time, policy, resource)",
    )
    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Specific constraint rule or limit value",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        nullable=False,
        doc="Structured additional parameters or metadata",
    )

    goal: Mapped["Goal"] = relationship("Goal", back_populates="constraints")


class GoalMilestone(BaseDBModel):
    """Structured milestone representing a discrete phase or milestone within a goal."""

    __tablename__ = "goal_milestones"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated goal identifier",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Milestone title",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Optional description of milestone deliverables",
    )
    status: Mapped[MilestoneStatus] = mapped_column(
        SQLAlchemyEnum(MilestoneStatus, name="milestone_status_enum"),
        default=MilestoneStatus.PENDING,
        nullable=False,
        doc="Progress state of the milestone",
    )
    order_index: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Ordering sequence for milestone progression",
    )
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Target completion timestamp for this milestone",
    )

    goal: Mapped["Goal"] = relationship("Goal", back_populates="milestones")
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="milestone")
