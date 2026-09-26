import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.goal import GoalPriority
from app.db.models.task import TaskStatus


class Weakness(BaseModel):
    """Categorized vulnerability, execution bottleneck, or risk factor in a plan."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the identified weakness",
    )
    category: str = Field(
        description="Classification code (e.g. BLOCKED_DEPENDENCY, DEADLINE_OVERDUE, RECENT_FAILURE, CRITICAL_PATH_BOTTLENECK, HIGH_WORKLOAD)"
    )
    severity: str = Field(description="Severity level: LOW, MEDIUM, HIGH, CRITICAL")
    description: str = Field(
        description="Detailed explanation of the issue and why it threatens goal success"
    )
    affected_task_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="IDs of tasks directly affected by this weakness",
    )
    mitigation_strategy: str = Field(
        description="Actionable remediation recommendation for the agent or user"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Diagnostic confidence in this finding [0.0 to 1.0]",
    )
    impact_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Potential negative impact on overall goal progress [0.0 to 1.0]",
    )


class RiskAssessment(BaseModel):
    """Comprehensive multi-dimensional risk diagnostic for a goal."""

    model_config = ConfigDict(from_attributes=True)

    overall_risk: str = Field(
        description="Overall synthesized risk tier: LOW, MEDIUM, HIGH, CRITICAL"
    )
    risk_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Synthesized composite risk score [0.0 to 1.0]",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in risk assessment based on available metrics [0.0 to 1.0]",
    )
    deadline_risk: str = Field(description="Deadline risk tier: LOW, MEDIUM, HIGH, CRITICAL")
    deadline_risk_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Deadline risk score [0.0 to 1.0]",
    )
    dependency_risk: str = Field(description="Dependency risk tier: LOW, MEDIUM, HIGH, CRITICAL")
    dependency_risk_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Dependency risk score [0.0 to 1.0]",
    )
    failure_risk: str = Field(description="Failure risk tier: LOW, MEDIUM, HIGH, CRITICAL")
    failure_risk_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Failure risk score [0.0 to 1.0]",
    )
    workload_risk: str = Field(
        description="Remaining workload risk tier: LOW, MEDIUM, HIGH, CRITICAL"
    )
    workload_risk_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Remaining workload risk score [0.0 to 1.0]",
    )
    primary_risk_factors: list[str] = Field(
        default_factory=list,
        description="List of primary risk triggers identified",
    )
    explanation: str = Field(
        description="Deterministic narrative explaining the risk assessment",
    )


class TaskEvaluation(BaseModel):
    """Detailed evaluation of an individual task within the goal plan."""

    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    goal_id: uuid.UUID
    title: str
    status: TaskStatus
    priority: GoalPriority
    weight: float = Field(
        ge=0.0,
        description="Computed multi-factor weight used in progress calculations",
    )
    estimated_minutes: int = Field(ge=0)
    actual_minutes: int | None = Field(default=None, ge=0)
    is_overdue: bool
    is_blocked: bool
    blocked_by_task_ids: list[uuid.UUID] = Field(default_factory=list)
    has_failed: bool
    failure_count: int = Field(default=0, ge=0)
    is_on_critical_path: bool
    performance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Execution efficiency and estimation accuracy [0.0 to 1.0]",
    )
    risk_level: str = Field(description="Task risk tier: LOW, MEDIUM, HIGH, CRITICAL")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in task evaluation [0.0 to 1.0]",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Specific problems or blockers detected for this task",
    )
    recommended_action: str = Field(
        description="Prescribed immediate next action for this task",
    )


class GoalEvaluation(BaseModel):
    """Complete structured goal plan evaluation result."""

    model_config = ConfigDict(from_attributes=True)

    goal_id: uuid.UUID
    user_id: uuid.UUID
    is_moving_forward: bool = Field(
        description="Primary determination: whether the current plan is actively progressing toward achievement"
    )
    completion_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Raw task completion fraction: completed_tasks / total_tasks",
    )
    weighted_progress: float = Field(
        ge=0.0,
        le=1.0,
        description="Priority, workload, and critical-path weighted progress [0.0 to 1.0]",
    )
    performance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Task execution efficiency, timeliness, and estimation quality [0.0 to 1.0]",
    )
    consistency_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Execution rhythm stability, lack of churning and blocking [0.0 to 1.0]",
    )
    deadline_risk: str = Field(description="Deadline risk tier: LOW, MEDIUM, HIGH, CRITICAL")
    remaining_workload_minutes: int = Field(
        ge=0,
        description="Estimated remaining uncompleted effort in minutes",
    )
    total_tasks: int = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    in_progress_tasks: int = Field(ge=0)
    blocked_tasks: int = Field(ge=0)
    failed_tasks: int = Field(ge=0)
    pending_tasks: int = Field(ge=0)
    blocked_dependencies_count: int = Field(
        ge=0,
        description="Total number of unresolved dependency links blocking progress",
    )
    recent_failures_count: int = Field(
        ge=0,
        description="Number of failed or repeatedly errored tasks",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall diagnostic confidence score [0.0 to 1.0]",
    )
    risk_assessment: RiskAssessment = Field(
        description="Deep multi-dimensional risk breakdown",
    )
    weaknesses: list[Weakness] = Field(
        default_factory=list,
        description="List of detected weaknesses sorted by severity and impact",
    )
    task_evaluations: list[TaskEvaluation] = Field(
        default_factory=list,
        description="Detailed evaluation per actionable task",
    )
    major_factors: list[str] = Field(
        default_factory=list,
        description="Major factors affecting progress and risk",
    )
    summary: str = Field(
        description="Concise executive diagnostic summary of plan progression",
    )
    recommended_action: str = Field(
        description="Highest priority strategic recommendation to move the goal forward",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional evaluation telemetry and parameters",
    )
