import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from lifethread_agent.types import AgentStatus, AgentStepType, DecisionType


class AgentDecision(BaseModel):
    """Structured decision produced by the agent reasoning phase."""

    decision_type: DecisionType = Field(
        ..., description="Taxonomy of the decision: call_tool, finish, wait_user, fail"
    )
    tool_name: str | None = Field(
        default=None, description="Name of the approved tool to invoke if CALL_TOOL"
    )
    tool_args: dict[str, Any] = Field(
        default_factory=dict, description="Arguments passed to the tool"
    )
    reasoning: str = Field(
        ..., description="Detailed explanation/rationale justifying this decision"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Auxiliary execution metadata"
    )

    def decision_signature(self) -> str:
        """Deterministic string signature used for loop and repetition detection."""
        args_sorted = sorted(self.tool_args.items(), key=lambda item: str(item[0]))
        return f"{self.decision_type}:{self.tool_name}:{str(args_sorted)}"


class ToolExecutionResult(BaseModel):
    """Outcome of an abstract tool execution invocation."""

    tool_name: str = Field(..., description="Name of the executed tool")
    success: bool = Field(..., description="Whether the tool completed successfully")
    result: Any = Field(default=None, description="Raw output returned by the tool")
    error: str | None = Field(default=None, description="Error message if execution failed")
    execution_time_ms: float = Field(
        default=0.0, ge=0.0, description="Execution duration in milliseconds"
    )


class StepEvaluation(BaseModel):
    """Evaluation of an action outcome assessing progress toward goal."""

    is_successful: bool = Field(..., description="Whether the step yielded a valid outcome")
    progress_made: bool = Field(..., description="Whether measurable forward progress was achieved")
    is_terminal: bool = Field(
        default=False, description="Whether the goal has reached a terminal completion or halt"
    )
    evaluation_notes: str = Field(..., description="Assessment findings and explanation")
    suggested_action: str | None = Field(
        default=None, description="Recommended adjustment or next step"
    )


class AgentStep(BaseModel):
    """Individual step executed during an agent run iteration."""

    step_number: int = Field(..., ge=0, description="Sequential index of this step in the run")
    phase: AgentStepType = Field(..., description="Phase within the agent loop")
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when step began",
    )
    completed_at: datetime | None = Field(default=None, description="Timestamp when step completed")
    input_state: dict[str, Any] | None = Field(
        default=None, description="Snapshot of state before step execution"
    )
    decision: AgentDecision | None = Field(default=None, description="Decision made if applicable")
    action_result: ToolExecutionResult | dict[str, Any] | None = Field(
        default=None, description="Result of tool execution if applicable"
    )
    evaluation: StepEvaluation | dict[str, Any] | None = Field(
        default=None, description="Evaluation findings if applicable"
    )
    output_state: dict[str, Any] | None = Field(
        default=None, description="Snapshot of state after step execution"
    )
    error: str | None = Field(
        default=None, description="Error details encountered during this step"
    )


class AgentState(BaseModel):
    """Pure domain state of an agent execution lifecycle.

    Contains zero database or ORM entities.
    """

    goal_id: str = Field(..., description="Target goal identifier")
    user_id: str = Field(..., description="Tenant user identifier")
    current_task_id: str | None = Field(
        default=None, description="Current sub-task under execution"
    )
    context: dict[str, Any] = Field(default_factory=dict, description="Working operational context")
    variables: dict[str, Any] = Field(
        default_factory=dict, description="State variables accumulated across iterations"
    )
    last_observation: dict[str, Any] | None = Field(
        default=None, description="Most recent observation payload"
    )
    last_evaluation: dict[str, Any] | None = Field(
        default=None, description="Most recent step evaluation"
    )
    is_terminal: bool = Field(
        default=False, description="Whether the agent has completed all possible work"
    )


class AgentRun(BaseModel):
    """Complete representation of an agent execution lifecycle run."""

    run_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), description="Unique run identifier"
    )
    goal_id: str = Field(..., description="Goal identifier")
    user_id: str = Field(..., description="Tenant user identifier")
    status: AgentStatus = Field(default=AgentStatus.PENDING, description="Current execution status")
    started_at: datetime | None = Field(
        default=None, description="Timestamp when run officially started"
    )
    completed_at: datetime | None = Field(
        default=None, description="Timestamp when run reached completion or termination"
    )
    current_step: int = Field(default=0, ge=0, description="Index of the current active step")
    iteration_count: int = Field(
        default=0, ge=0, description="Total completed iterations through the agent loop"
    )
    error: str | None = Field(
        default=None, description="Fatal or terminal error description if failed"
    )
    state: AgentState = Field(..., description="Latest working state snapshot")
    steps: list[AgentStep] = Field(
        default_factory=list, description="Sequence of all recorded steps in this run"
    )
    trace: list[dict[str, Any]] = Field(
        default_factory=list, description="Append-only log of execution events and audit traces"
    )
