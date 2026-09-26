import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.goal import GoalPriority
from app.db.models.task import TaskStatus


class WeaknessItem(BaseModel):
    """Categorized vulnerability, risk factor, or execution bottleneck in a plan."""

    category: str = Field(..., description="Category code (e.g. OVERDUE_TASK, BLOCKED_EXECUTION)")
    severity: str = Field(..., description="Severity level: LOW, MEDIUM, HIGH, CRITICAL")
    description: str = Field(..., description="Actionable explanation of the weakness")
    affected_task_ids: list[uuid.UUID] = Field(
        default_factory=list, description="IDs of tasks impacted by this issue"
    )
    mitigation_strategy: str = Field(
        ..., description="Recommended mitigation action for agent or user"
    )


class GoalProgressEvaluation(BaseModel):
    """Structured holistic progress evaluation of a goal."""

    goal_id: uuid.UUID
    goal_progress: float = Field(
        ..., ge=0.0, le=1.0, description="Priority-weighted progress score between 0.0 and 1.0"
    )
    raw_task_progress: float = Field(
        ..., ge=0.0, le=1.0, description="Simple completion ratio: completed_tasks / total_tasks"
    )
    total_tasks: int = Field(..., ge=0)
    completed_tasks: int = Field(..., ge=0)
    in_progress_tasks: int = Field(..., ge=0)
    pending_tasks: int = Field(..., ge=0)
    blocked_tasks: int = Field(..., ge=0)
    cancelled_tasks: int = Field(..., ge=0)
    remaining_workload_minutes: int = Field(..., ge=0)
    deadline_risk: str = Field(
        ..., description="Deadline risk category: low, medium, high, critical"
    )
    weaknesses: list[str] = Field(
        default_factory=list, description="Summary descriptions of detected weaknesses"
    )
    recommended_action: str = Field(..., description="Strategic next step recommendation")

    model_config = ConfigDict(from_attributes=True)


class TaskEvaluation(BaseModel):
    """Detailed diagnostic evaluation of an individual task."""

    task_id: uuid.UUID
    goal_id: uuid.UUID
    title: str
    status: TaskStatus
    priority: GoalPriority
    estimated_minutes: int
    is_overdue: bool
    is_blocked_by_prerequisites: bool
    uncompleted_prerequisites: list[dict[str, Any]] = Field(default_factory=list)
    dependent_tasks_count: int = Field(
        ..., ge=0, description="Number of successor tasks waiting on this task"
    )
    is_on_critical_path: bool = Field(
        ..., description="Whether this task is on the project critical path"
    )
    risk_level: str = Field(..., description="Risk category: low, medium, high, critical")
    issues: list[str] = Field(
        default_factory=list, description="List of identified issues or blockers"
    )
    recommended_action: str = Field(..., description="Recommended next action for this task")

    model_config = ConfigDict(from_attributes=True)


class GoalWeaknessesEvaluation(BaseModel):
    """Structured weaknesses assessment across all tasks in a goal."""

    goal_id: uuid.UUID
    weaknesses: list[WeaknessItem] = Field(default_factory=list)
    weakness_count: int = Field(..., ge=0)
    overall_health: str = Field(
        ...,
        description="Overall health classification: HEALTHY, NEEDS_ATTENTION, AT_RISK, CRITICAL",
    )
    recommended_action: str = Field(..., description="Highest-priority remediation action")

    model_config = ConfigDict(from_attributes=True)


class GoalRiskEvaluation(BaseModel):
    """Multivariate risk calculation quantifying project exposure."""

    goal_id: uuid.UUID
    composite_risk_score: float = Field(
        ..., ge=0.0, le=1.0, description="Normalized composite risk score between 0.0 and 1.0"
    )
    deadline_risk: str = Field(..., description="Risk rating: low, medium, high, critical")
    schedule_risk_score: float = Field(..., ge=0.0, le=1.0)
    dependency_risk_score: float = Field(..., ge=0.0, le=1.0)
    priority_risk_score: float = Field(..., ge=0.0, le=1.0)
    risk_factors: list[str] = Field(
        default_factory=list, description="Identified risk contributing factors"
    )
    recommended_action: str = Field(..., description="Recommended risk mitigation action")

    model_config = ConfigDict(from_attributes=True)
