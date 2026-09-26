import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession


class FailureBehavior(StrEnum):
    """Defined behavior when a skill execution encounters an unexpected failure."""

    FAIL_FAST = "FAIL_FAST"
    GRACEFUL_DEGRADATION = "GRACEFUL_DEGRADATION"
    FALLBACK_DEFAULT = "FALLBACK_DEFAULT"
    ROLLBACK_AND_NOTIFY = "ROLLBACK_AND_NOTIFY"


class SkillCategory(StrEnum):
    """Categorical classification of reusable agent skills."""

    GOAL_MANAGEMENT = "GOAL_MANAGEMENT"
    PLANNING = "PLANNING"
    MEMORY = "MEMORY"
    EVALUATION = "EVALUATION"
    REPLANNING = "REPLANNING"
    COMPOSITE = "COMPOSITE"


class SkillMetadata(BaseModel):
    """Introspective metadata defining a skill's purpose, contracts, permissions, and tools."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    purpose: str
    category: SkillCategory
    required_permissions: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    failure_behavior: FailureBehavior
    inputs_schema: dict[str, Any] = Field(default_factory=dict)
    outputs_schema: dict[str, Any] = Field(default_factory=dict)


class SkillExecutionContext(BaseModel):
    """Execution context provided to a skill invocation, carrying identity, permissions, and tracing."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: uuid.UUID
    db: AsyncSession
    session_id: str | None = None
    goal_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    run_id: str | None = None
    user_permissions: set[str] = Field(default_factory=set)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillResult(BaseModel):
    """Structured result returned by any skill execution."""

    model_config = ConfigDict(from_attributes=True)

    skill_name: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    failure_behavior_applied: FailureBehavior | None = None
    execution_time_ms: float = 0.0
    trace_events: list[str] = Field(default_factory=list)
    subskills_executed: list["SkillResult"] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SkillPipelineStep(BaseModel):
    """Individual step within a composable skill pipeline."""

    skill_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    pass_previous_output_key: str | None = Field(
        default=None,
        description="If set, maps output of previous step into inputs under this key",
    )


class SkillPipelineRequest(BaseModel):
    """Request payload to execute a sequential composable skill pipeline."""

    steps: list[SkillPipelineStep]
    stop_on_failure: bool = True
    goal_id: uuid.UUID | None = None


class SkillPipelineResult(BaseModel):
    """Result of executing a composable skill pipeline."""

    success: bool
    total_steps: int
    completed_steps: int
    step_results: list[SkillResult] = Field(default_factory=list)
    final_output: dict[str, Any] = Field(default_factory=dict)
    total_time_ms: float = 0.0
    error: str | None = None
