import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionEventType(StrEnum):
    """Execution event types spanning the agent reasoning and action lifecycle."""

    AGENT_RUN = "AGENT_RUN"
    DECISION = "DECISION"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    EVALUATION = "EVALUATION"
    STATE_UPDATE = "STATE_UPDATE"
    REPLANNING = "REPLANNING"


class TraceStage(StrEnum):
    """The 10 canonical stages required by Module 37 for complete agent run reconstruction."""

    INPUT = "input"
    SELECTED_CONTEXT = "selected_context"
    RETRIEVED_MEMORIES = "retrieved_memories"
    SELECTED_TOOLS = "selected_tools"
    TOOL_CALLS = "tool_calls"
    TOOL_RESULTS = "tool_results"
    EVALUATION = "evaluation"
    STATE_CHANGES = "state_changes"
    REPLANNING_EVENT = "replanning_event"
    FINAL_RESULT = "final_result"


class EventStatus(StrEnum):
    """Terminal or transient status of an execution event or run."""

    SUCCESS = "SUCCESS"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"


class CoTSanitizer:
    """Guarantees that private chain-of-thought and hidden model reasoning are NEVER stored."""

    COT_PATTERNS = [
        re.compile(r"<thought>.*?</thought>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<scratchpad>.*?</scratchpad>", re.DOTALL | re.IGNORECASE),
        re.compile(r"\[private_reasoning\].*?\[/private_reasoning\]", re.DOTALL | re.IGNORECASE),
        re.compile(r"\[Chain-of-Thought\].*?\[/Chain-of-Thought\]", re.DOTALL | re.IGNORECASE),
        re.compile(r"\[Chain-of-Thought\][^\n]*(?:\n\n|\Z)", re.IGNORECASE),
    ]

    SECRET_PATTERNS = [
        (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
        (re.compile(r"sk-(?:proj-)?[a-zA-Z0-9_-]{15,}"), "[REDACTED_API_KEY]"),
        (re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{25,}", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    ]

    COT_KEYS = {
        "cot",
        "chain_of_thought",
        "internal_reasoning",
        "private_reasoning",
        "thinking",
        "scratchpad",
        "raw_prompt_history",
        "hidden_thoughts",
        "raw_thought",
        "raw_thoughts",
        "model_thoughts",
    }

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """Strip raw hidden reasoning patterns and mask high-entropy secrets."""
        if not text:
            return ""
        sanitized = text
        for pat in cls.COT_PATTERNS:
            sanitized = pat.sub("", sanitized)
        for sec_pat, mask in cls.SECRET_PATTERNS:
            sanitized = sec_pat.sub(mask, sanitized)
        return sanitized.strip()

    @classmethod
    def sanitize_payload(cls, data: Any) -> Any:
        """Recursively strip private reasoning keys and hidden CoT strings."""
        if isinstance(data, dict):
            clean: dict[str, Any] = {}
            for k, v in data.items():
                if k.lower() in cls.COT_KEYS:
                    continue
                clean[k] = cls.sanitize_payload(v)
            return clean
        elif isinstance(data, list):
            return [cls.sanitize_payload(item) for item in data]
        elif isinstance(data, str):
            return cls.sanitize_text(data)
        return data


class AgentExecutionEvent(BaseModel):
    """Single discrete event in an agent execution trace.

    Strictly user-facing: Safe explanations only, no raw hidden model reasoning.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    trace_id: str | None = None
    correlation_id: str | None = None
    stage: TraceStage | None = None
    user_id: uuid.UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: ExecutionEventType
    status: EventStatus = EventStatus.SUCCESS
    short_explanation: str
    goal_id: uuid.UUID | None = None
    goal_title: str | None = None
    task_id: uuid.UUID | None = None
    task_title: str | None = None
    tool_name: str | None = None
    tool_parameters: dict[str, Any] = Field(default_factory=dict)
    tool_result: dict[str, Any] = Field(default_factory=dict)
    state_changes: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRun(BaseModel):
    """Structured container of an autonomous agent execution run."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: uuid.UUID
    trigger: str = "MANUAL"
    status: EventStatus = EventStatus.RUNNING
    goal_id: uuid.UUID | None = None
    goal_title: str | None = None
    task_id: uuid.UUID | None = None
    task_title: str | None = None
    summary: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_ms: int | None = None
    events: list[AgentExecutionEvent] = Field(default_factory=list)
    stages_data: dict[str, Any] = Field(default_factory=dict)


class AgentRunSummary(BaseModel):
    """Compact summary of an execution run for listing views."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    trace_id: str | None = None
    correlation_id: str | None = None
    user_id: uuid.UUID
    trigger: str
    status: EventStatus
    goal_id: uuid.UUID | None = None
    goal_title: str | None = None
    task_id: uuid.UUID | None = None
    task_title: str | None = None
    summary: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    event_count: int = 0


class ReconstructedAgentTrace(BaseModel):
    """Complete 10-stage execution trace enabling complete reconstruction of an agent run."""

    model_config = ConfigDict(from_attributes=True)

    trace_id: str
    correlation_id: str
    run_id: str
    user_id: uuid.UUID
    trigger: str
    status: EventStatus
    goal_id: uuid.UUID | None = None
    goal_title: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None

    # The 10 Trace Lifecycle Components (Module 37)
    input: dict[str, Any] = Field(default_factory=dict, description="1. Initial user input or event trigger")
    selected_context: dict[str, Any] = Field(default_factory=dict, description="2. Active goal, task, and session context")
    retrieved_memories: list[dict[str, Any]] = Field(default_factory=list, description="3. User memories and preferences loaded")
    selected_tools: list[str] = Field(default_factory=list, description="4. Skills and tools selected for the run")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, description="5. Explicit tool invocations with sanitized parameters")
    tool_results: list[dict[str, Any]] = Field(default_factory=list, description="6. Tool outcomes and execution payloads")
    evaluation: dict[str, Any] | None = Field(default=None, description="7. Progress, deadline risk, and blocker evaluation")
    state_changes: dict[str, Any] = Field(default_factory=dict, description="8. Database and domain state mutations")
    replanning_event: dict[str, Any] | None = Field(default=None, description="9. Replanning trigger, diff, and feasibility rationale")
    final_user_facing_result: dict[str, Any] = Field(default_factory=dict, description="10. Final user-facing message and cards (no private CoT)")

    # Chronological execution timeline
    events: list[AgentExecutionEvent] = Field(default_factory=list)
    is_reconstructible: bool = True
