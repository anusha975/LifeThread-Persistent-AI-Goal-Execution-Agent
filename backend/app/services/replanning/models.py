import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.goal import GoalPriority


class ReplanningReason(StrEnum):
    """Trigger reasons that cause a plan validity re-evaluation and potential replan."""

    DEADLINE_CHANGED = "DEADLINE_CHANGED"
    AVAILABLE_TIME_CHANGED = "AVAILABLE_TIME_CHANGED"
    TASK_FAILED = "TASK_FAILED"
    TASK_BLOCKED = "TASK_BLOCKED"
    NEW_REQUIREMENT = "NEW_REQUIREMENT"
    NEW_WEAKNESS_DISCOVERED = "NEW_WEAKNESS_DISCOVERED"
    DEPENDENCY_CHANGED = "DEPENDENCY_CHANGED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"


class ReplanningEvent(BaseModel):
    """Structured event capturing a real-world state or constraint change."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the replanning trigger event",
    )
    goal_id: uuid.UUID = Field(description="Target goal identifier")
    user_id: uuid.UUID = Field(description="Target user identifier")
    reason: ReplanningReason = Field(description="Trigger classification")
    description: str = Field(description="Human-readable summary of the real-world change")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Specific parameters of the change (e.g. old/new deadlines, failed task ID, new hours)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event occurrence timestamp in UTC",
    )


class TaskRescheduleItem(BaseModel):
    """Details of a task that was rescheduled during replanning."""

    task_id: uuid.UUID
    title: str
    priority: GoalPriority
    old_start: datetime | None
    new_start: datetime
    old_end: datetime | None
    new_end: datetime
    shift_hours: float = Field(
        description="Net delta in start time (positive = delayed, negative = moved earlier)"
    )
    rationale: str = Field(description="Specific scheduling explanation for this task")


class PriorityChangeItem(BaseModel):
    """Details of a task whose execution priority was updated between plan versions."""

    task_id: uuid.UUID
    title: str
    old_priority: GoalPriority
    new_priority: GoalPriority
    rationale: str = Field(
        default="Priority adjusted to align with updated plan dependencies and critical path",
        description="Explanation for priority adjustment",
    )


class PlanDiff(BaseModel):
    """Detailed structural diff comparing the previous plan version against the new plan version."""

    model_config = ConfigDict(from_attributes=True)

    old_plan_version: int | None = Field(
        default=None,
        description="Version number of the previous plan (None if initial plan)",
    )
    new_plan_version: int = Field(description="Version number of the new candidate/committed plan")
    why_changed: str = Field(
        description="WHY THE PLAN CHANGED: Root cause justification triggering the revision"
    )
    what_changed: str = Field(description="WHAT CHANGED: High-level summary of structural changes")
    tasks_added: list[dict[str, Any]] = Field(
        default_factory=list,
        description="WHAT WAS ADDED: New tasks incorporated into the schedule",
    )
    tasks_removed: list[dict[str, Any]] = Field(
        default_factory=list,
        description="WHAT WAS REMOVED: Deprioritized, cancelled, or eliminated tasks",
    )
    tasks_rescheduled: list[TaskRescheduleItem] = Field(
        default_factory=list,
        description="WHAT WAS RESCHEDULED: Tasks with adjusted execution time windows",
    )
    priority_changes: list[PriorityChangeItem] = Field(
        default_factory=list,
        description="WHAT PRIORITIES CHANGED: Tasks whose execution priority was shifted",
    )
    tasks_unaffected: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Tasks whose scheduled time slots remained unchanged",
    )
    critical_path_changed: bool = Field(
        default=False,
        description="Whether the composition of the critical path altered",
    )
    old_critical_path_task_ids: list[uuid.UUID] = Field(default_factory=list)
    new_critical_path_task_ids: list[uuid.UUID] = Field(default_factory=list)
    old_risk_level: str = Field(default="LOW")
    new_risk_level: str = Field(default="LOW")
    old_completion_date: datetime | None = None
    new_completion_date: datetime | None = None
    why_feasible: str = Field(
        description="WHY THE NEW PLAN IS FEASIBLE: Proof and operational rationale demonstrating feasibility"
    )


class PlanComparisonSummary(BaseModel):
    """Real snapshot metrics comparing historical plan versions."""

    version: int
    task_count: int
    total_duration_minutes: int
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    risk_level: str
    is_feasible: bool
    status: str
    items: list[dict[str, Any]] = Field(default_factory=list)


class ReplanningDiffResponse(BaseModel):
    """Comprehensive visual Plan Diff payload matching Module 31 specification."""

    plan_changed: bool = Field(description="True if a plan modification has occurred")
    status_label: str = Field(default="PLAN CHANGED", description="Standard display banner")
    reason: str = Field(description="Actual reason triggering the plan change")
    why_explanation: str = Field(
        description="WHY? Concise user-facing explanation based on actual replanning metadata (no private CoT)"
    )
    why_feasible: str = Field(
        description="Operational rationale proving why the new plan is viable"
    )
    previous_plan: PlanComparisonSummary | None = None
    new_plan: PlanComparisonSummary | None = None
    changes: PlanDiff | None = None
    priority_changes: list[PriorityChangeItem] = Field(default_factory=list)
    committed_at: datetime | None = None


class ReplanningDecision(BaseModel):
    """Result of an autonomous replanning evaluation, documenting action, diff, and rationale."""

    model_config = ConfigDict(from_attributes=True)

    decision_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this replanning decision",
    )
    goal_id: uuid.UUID
    user_id: uuid.UUID
    event: ReplanningEvent
    replanning_required: bool = Field(
        description="Whether the change invalidated the current plan and required replanning"
    )
    action_taken: str = Field(
        description="Outcome classification: PLAN_COMMITTED, PLAN_PREVIEWED, NO_REPLANNING_NEEDED, INFEASIBLE_ALERT"
    )
    previous_plan_version: int | None = None
    new_plan_version: int | None = None
    is_feasible: bool = Field(
        default=True,
        description="Whether the resulting plan satisfies all constraints and deadlines",
    )
    diff: PlanDiff | None = Field(
        default=None,
        description="Explainable diff detailing what changed between versions",
    )
    impact_analysis: dict[str, Any] = Field(
        default_factory=dict,
        description="Quantitative impact metrics (affected task count, workload delta, risk shift)",
    )
    explanation: str = Field(
        description="Comprehensive narrative explaining the decision and why the new plan is viable",
    )
    committed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Decision execution timestamp in UTC",
    )
