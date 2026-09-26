import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.models.base import BaseDBModel
from app.db.models.goal import GoalPriority

if TYPE_CHECKING:
    from app.db.models.goal import Goal, GoalMilestone
    from app.db.models.plan import PlanItem


class TaskStatus(StrEnum):
    """Lifecycle execution statuses for a decomposition task."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class Task(BaseDBModel):
    """Actionable atomic unit of work decomposed from a Goal."""

    __tablename__ = "tasks"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Parent goal identifier",
    )
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("goal_milestones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Associated milestone phase identifier",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        index=True,
        doc="Decomposition revision version number",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Concise, actionable task description",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Detailed implementation notes and instructions",
    )
    status: Mapped[TaskStatus] = mapped_column(
        SQLAlchemyEnum(TaskStatus, name="task_status_enum"),
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
        doc="Current execution status",
    )
    priority: Mapped[GoalPriority] = mapped_column(
        SQLAlchemyEnum(GoalPriority, name="goal_priority_enum"),
        default=GoalPriority.MEDIUM,
        nullable=False,
        doc="Execution priority",
    )
    estimated_minutes: Mapped[int] = mapped_column(
        Integer,
        default=60,
        nullable=False,
        doc="Estimated effort duration in minutes",
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Optional deadline timestamp in UTC",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of task completion in UTC",
    )

    # Relationships
    goal: Mapped["Goal"] = relationship("Goal", back_populates="tasks")
    milestone: Mapped["GoalMilestone | None"] = relationship(
        "GoalMilestone", back_populates="tasks"
    )

    outgoing_dependencies: Mapped[list["TaskDependency"]] = relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.task_id",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    incoming_dependencies: Mapped[list["TaskDependency"]] = relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.depends_on_task_id",
        back_populates="depends_on_task",
        cascade="all, delete-orphan",
    )
    plan_items: Mapped[list["PlanItem"]] = relationship(
        "PlanItem",
        back_populates="task",
        cascade="all, delete-orphan",
    )


class TaskDependency(BaseDBModel):
    """Directed dependency link between two tasks (task depends on depends_on_task)."""

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),
        CheckConstraint("task_id != depends_on_task_id", name="ck_task_not_self_dependent"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Task that depends on another prerequisite task",
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Prerequisite task that must finish before task can proceed",
    )
    dependency_type: Mapped[str] = mapped_column(
        String(50),
        default="BLOCKS",
        nullable=False,
        doc="Dependency relationship type (e.g. BLOCKS, REQUIRES)",
    )

    # Relationships
    task: Mapped["Task"] = relationship(
        "Task",
        foreign_keys=[task_id],
        back_populates="outgoing_dependencies",
    )
    depends_on_task: Mapped["Task"] = relationship(
        "Task",
        foreign_keys=[depends_on_task_id],
        back_populates="incoming_dependencies",
    )


class GoalDecomposition(BaseDBModel):
    """Historical decomposition revision snapshot associated with a goal."""

    __tablename__ = "goal_decompositions"
    __table_args__ = (UniqueConstraint("goal_id", "version", name="uq_goal_decomposition_version"),)

    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated goal identifier",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Monotonically increasing decomposition revision number",
    )
    task_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Total number of tasks in this decomposition revision",
    )
    critical_path_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Total duration of the critical path in minutes",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether this decomposition version is the active plan",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        nullable=False,
        doc="Decomposition metrics, critical path node IDs, and parameters",
    )

    # Relationships
    goal: Mapped["Goal"] = relationship("Goal", back_populates="decompositions")
