import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.memory import MemoryType


class LearningType(StrEnum):
    """Classification of learning outcome."""

    WEAKNESS = "WEAKNESS"
    STRENGTH = "STRENGTH"
    PREFERENCE = "PREFERENCE"
    NEUTRAL_ROUTINE = "NEUTRAL_ROUTINE"


class ExecutionStatus(StrEnum):
    """Execution outcome status."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    CANCELLED = "CANCELLED"


class ExecutionOutcome(BaseModel):
    """Structured capture of a real-world task or agent action execution result."""

    model_config = ConfigDict(from_attributes=True)

    outcome_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this execution outcome event",
    )
    user_id: uuid.UUID = Field(description="Target user ID for multi-tenant isolation")
    goal_id: uuid.UUID | None = Field(default=None, description="Optional associated goal ID")
    task_id: uuid.UUID | None = Field(default=None, description="Optional associated task ID")
    task_title: str = Field(default="Task Execution", description="Human-readable title of task")
    domain: str | None = Field(
        default=None,
        description="Knowledge or skill domain (e.g. 'SQL', 'Python', 'Machine Learning')",
    )
    topic: str | None = Field(
        default=None,
        description="Granular topic or skill (e.g. 'joins', 'indexing', 'recursion')",
    )
    action_type: str = Field(
        default="TASK_EXECUTION",
        description="Action nature (e.g. 'TASK_EXECUTION', 'STUDY_SESSION', 'EXERCISE', 'TEST_RUN')",
    )
    status: ExecutionStatus | str = Field(
        default=ExecutionStatus.COMPLETED,
        description="Terminal status of the execution (COMPLETED, FAILED, BLOCKED, etc.)",
    )
    performance_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Quantified score or accuracy between 0.0 and 1.0",
    )
    actual_minutes: int | None = Field(
        default=None,
        ge=0,
        description="Actual execution duration in minutes",
    )
    expected_minutes: int | None = Field(
        default=None,
        ge=0,
        description="Planned or estimated duration in minutes",
    )
    error_message: str | None = Field(
        default=None,
        description="Error details or exception trace if task encountered failures",
    )
    notes: str | None = Field(
        default=None,
        description="Qualitative observations or user/agent execution remarks",
    )
    artifacts: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution artifacts (e.g. sub-scores, error codes, code snippets)",
    )
    attempt_count: int = Field(
        default=1,
        ge=1,
        description="Number of attempts or repetitions observed for this task/topic",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of execution outcome",
    )


class OutcomeEvaluation(BaseModel):
    """Structured evaluation of an execution outcome, determining memory conversion eligibility."""

    model_config = ConfigDict(from_attributes=True)

    outcome_id: str = Field(description="Reference to source execution outcome")
    is_meaningful: bool = Field(
        description="Whether outcome carries meaningful information worth long-term retention"
    )
    evaluation_type: LearningType = Field(
        description="Classification: WEAKNESS, STRENGTH, PREFERENCE, NEUTRAL_ROUTINE"
    )
    observed_finding: str = Field(
        description="Concise description of the finding (e.g. 'Weakness in SQL joins')"
    )
    severity_or_strength: str = Field(
        default="MEDIUM",
        description="Magnitude of the finding: LOW, MEDIUM, HIGH, CRITICAL",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score in this evaluation [0.0 to 1.0]",
    )
    importance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Importance score for memory conversion [0.0 to 1.0]",
    )
    is_factual: bool = Field(
        default=False,
        description="Strictly False if uncertain or provisional; True only for verified facts",
    )
    is_hypothesis: bool = Field(
        default=True,
        description="True if finding is a provisional hypothesis requiring further confirmation",
    )
    epistemic_qualifier: str = Field(
        default="Provisional hypothesis",
        description="Epistemic status label (e.g. 'Verified fact', 'Provisional hypothesis', 'Low-confidence observation')",
    )
    target_memory_type: MemoryType = Field(
        default=MemoryType.SEMANTIC,
        description="Target memory classification: SEMANTIC, EPISODIC, PREFERENCE, GOAL",
    )
    suggested_memory_content: str = Field(
        description="Text content recommended for persistent memory record"
    )
    recommended_planner_action: str | None = Field(
        default=None,
        description="Recommended adaptation for future planners (e.g. 'Increase SQL joins practice')",
    )
    reasoning: str = Field(description="Explanation of how evaluation was derived")


class LearningMemoryLink(BaseModel):
    """Metadata linking a persistent memory to its originating execution and goal context."""

    goal_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    task_title: str | None = None
    domain: str | None = None
    topic: str | None = None
    outcome_id: str
    learning_type: LearningType
    confidence: float
    is_hypothesis: bool
    is_factual: bool
    recommended_action: str | None = None
    recorded_at: str


class LearningImpact(BaseModel):
    """Record of how a retrieved learning memory influenced a future planning decision."""

    memory_id: uuid.UUID
    memory_content: str
    domain: str | None = None
    topic: str | None = None
    target_task_id: uuid.UUID | None = None
    target_task_title: str
    adjustment_type: str = Field(
        description="Nature of adjustment (e.g. 'INCREASE_PRACTICE', 'INCREASE_DURATION', 'ELEVATE_PRIORITY', 'INJECT_REINFORCEMENT_TASK')"
    )
    details: str = Field(description="Detailed narrative of what was adjusted and why")
    confidence: float = Field(description="Confidence of memory that motivated this decision")


class LearningPlanningResult(BaseModel):
    """Result of applying past learnings and memory outcomes to future planning."""

    goal_id: uuid.UUID
    user_id: uuid.UUID
    relevant_memories_count: int
    memories_applied: list[LearningImpact] = Field(default_factory=list)
    tasks_modified_count: int = 0
    tasks_injected_count: int = 0
    summary_rationale: str
