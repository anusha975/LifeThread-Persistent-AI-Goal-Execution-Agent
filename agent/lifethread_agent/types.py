from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    """Lifecycle status for an agent execution run."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


# Backward compatibility alias
ExecutionStatus = AgentStatus


class AgentStepType(StrEnum):
    """Phases of the canonical agent execution loop."""

    OBSERVE = "observe"
    UNDERSTAND = "understand"
    DECIDE = "decide"
    ACT = "act"
    EVALUATE = "evaluate"
    UPDATE_STATE = "update_state"


class DecisionType(StrEnum):
    """Actionable decision taxonomy output by the agent reasoning step."""

    CALL_TOOL = "call_tool"
    FINISH = "finish"
    WAIT_USER = "wait_user"
    FAIL = "fail"


class AgentContext(BaseModel):
    """Pure domain context passed into orchestrator workflows.

    Contains no database entities or ORM instances.
    """

    goal_id: str = Field(..., description="Unique identifier for the goal being orchestrated")
    session_id: str = Field(..., description="Current session or turn identifier")
    user_id: str = Field(default="default-user", description="Identifier of the user")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Domain metadata required for context tracking",
    )


class OrchestratorResult(BaseModel):
    """Outcome of an orchestrator evaluation step."""

    status: AgentStatus = Field(..., description="Resulting execution state")
    step_count: int = Field(default=0, ge=0, description="Number of execution iterations performed")
    summary: str | None = Field(default=None, description="Descriptive summary of the step result")
    run_id: str | None = Field(default=None, description="Identifier of the agent run")
