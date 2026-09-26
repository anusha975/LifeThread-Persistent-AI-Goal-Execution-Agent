import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.goal import GoalPriority
from app.db.models.task import TaskStatus
from app.schemas.goal import GoalMilestoneResponse


class TaskBase(BaseModel):
    """Base schema for task properties."""

    title: str = Field(
        ..., min_length=1, max_length=255, description="Concise, actionable task title"
    )
    description: str | None = Field(
        default=None, description="Detailed guidance or acceptance notes"
    )
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current execution status")
    priority: GoalPriority = Field(
        default=GoalPriority.MEDIUM, description="Task execution priority"
    )
    estimated_minutes: int = Field(default=60, ge=1, description="Estimated effort in minutes")
    due_at: datetime | None = Field(default=None, description="Target completion timestamp in UTC")


class TaskCreate(TaskBase):
    """Payload to create an individual task."""

    milestone_id: uuid.UUID | None = Field(
        default=None, description="Optional associated milestone ID"
    )


class TaskUpdate(BaseModel):
    """Payload to update mutable fields on a task."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: TaskStatus | None = None
    priority: GoalPriority | None = None
    estimated_minutes: int | None = Field(default=None, ge=1)
    due_at: datetime | None = None


class TaskResponse(TaskBase):
    """Public representation of an execution task."""

    id: uuid.UUID
    goal_id: uuid.UUID
    milestone_id: uuid.UUID | None
    version: int
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskListResponse(BaseModel):
    """Collection response for goal tasks."""

    goal_id: uuid.UUID
    version: int
    items: list[TaskResponse]
    total: int


class TaskDependencyResponse(BaseModel):
    """Public representation of a task dependency link."""

    id: uuid.UUID
    task_id: uuid.UUID
    depends_on_task_id: uuid.UUID
    dependency_type: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DecompositionRequest(BaseModel):
    """Options for generating or revising a goal decomposition."""

    confirm_new_version: bool = Field(
        default=False,
        description="Explicit confirmation flag required if a previous decomposition already exists",
    )
    max_tasks: int = Field(
        default=20,
        ge=2,
        le=50,
        description="Upper bound of tasks to generate",
    )


class GoalDecompositionResponse(BaseModel):
    """Comprehensive result of a goal decomposition."""

    goal_id: uuid.UUID
    version: int
    is_active: bool
    milestones: list[GoalMilestoneResponse]
    tasks: list[TaskResponse]
    dependencies: list[TaskDependencyResponse]
    critical_path_task_ids: list[uuid.UUID]
    critical_path_duration_minutes: int
    has_cycles: bool = False
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class TaskDependencyGraphResponse(BaseModel):
    """Graph structure of goal tasks and directed dependency edges."""

    goal_id: uuid.UUID
    version: int
    nodes: list[TaskResponse]
    edges: list[TaskDependencyResponse]
    critical_path: list[uuid.UUID]
    topological_order: list[uuid.UUID]
    critical_path_duration_minutes: int
