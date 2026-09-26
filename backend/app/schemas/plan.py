import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.goal import GoalPriority
from app.db.models.plan import PlanStatus


class PlanItemResponse(BaseModel):
    """Scheduled task time slot within a concrete plan version."""

    id: uuid.UUID
    plan_id: uuid.UUID
    task_id: uuid.UUID
    task_title: str | None = Field(
        default=None, description="Human-readable title of the assigned task"
    )
    scheduled_start: datetime = Field(..., description="Scheduled start timestamp in UTC")
    scheduled_end: datetime = Field(..., description="Scheduled finish timestamp in UTC")
    priority: GoalPriority = Field(
        default=GoalPriority.MEDIUM, description="Task execution priority"
    )
    rationale: str | None = Field(
        default=None,
        description="Justification explaining why this task is scheduled at this window",
    )

    model_config = ConfigDict(from_attributes=True)


class PlanCreateRequest(BaseModel):
    """Configuration options for scheduling a goal plan."""

    daily_available_hours: float = Field(
        default=4.0,
        ge=0.5,
        le=24.0,
        description="User available work time per day in hours",
    )
    start_date: datetime | None = Field(
        default=None,
        description="Optional schedule start timestamp in UTC (defaults to current time)",
    )
    workdays_only: bool = Field(
        default=True,
        description="Whether to schedule work exclusively on weekdays (Mon-Fri)",
    )
    daily_start_hour: int = Field(
        default=9,
        ge=0,
        le=23,
        description="Local hour of day to open work windows (e.g. 9 for 09:00)",
    )
    reason: str | None = Field(
        default=None,
        description="Optional trigger reason or commentary for this plan generation",
    )


class PlanResponse(BaseModel):
    """Comprehensive plan specification and schedule."""

    id: uuid.UUID
    goal_id: uuid.UUID
    version: int
    status: PlanStatus
    generated_at: datetime
    reason: str | None
    is_feasible: bool = Field(
        ..., description="Whether the plan completes before the goal deadline"
    )
    deadline_risk: float = Field(..., description="Deadline risk score (0.0 to 1.0+)")
    risk_level: str = Field(..., description="Categorical risk rating: LOW, MEDIUM, HIGH, CRITICAL")
    schedule_utilization: float = Field(
        ..., description="Workload to available capacity utilization ratio"
    )
    total_duration_minutes: int
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    items: list[PlanItemResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PlanSummaryResponse(BaseModel):
    """Compact summary of a historical plan version."""

    id: uuid.UUID
    goal_id: uuid.UUID
    version: int
    status: PlanStatus
    generated_at: datetime
    reason: str | None
    is_feasible: bool
    risk_level: str
    total_duration_minutes: int
    task_count: int
    scheduled_start: datetime | None
    scheduled_end: datetime | None

    model_config = ConfigDict(from_attributes=True)


class PlanListResponse(BaseModel):
    """Collection of historical plan versions for a goal."""

    goal_id: uuid.UUID
    items: list[PlanSummaryResponse]
    total: int
