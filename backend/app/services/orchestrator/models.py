import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentIntent(StrEnum):
    """Classified user intent for conversational execution."""

    CREATE_GOAL = "CREATE_GOAL"
    NEXT_ACTION = "NEXT_ACTION"
    WHAT_CHANGED = "WHAT_CHANGED"
    WHY_PLAN_CHANGED = "WHY_PLAN_CHANGED"
    CAPACITY_CONSTRAINT = "CAPACITY_CONSTRAINT"
    REMEMBER_FACT = "REMEMBER_FACT"
    WHAT_IS_BLOCKING = "WHAT_IS_BLOCKING"
    COMPLETE_TASK = "COMPLETE_TASK"
    SWITCH_GOAL = "SWITCH_GOAL"
    CHANGE_DEADLINE = "CHANGE_DEADLINE"
    UPDATE_PRIORITY = "UPDATE_PRIORITY"
    CLARIFICATION_ANSWER = "CLARIFICATION_ANSWER"
    MILESTONE_QUERY = "MILESTONE_QUERY"
    MEMORY_QUERY = "MEMORY_QUERY"
    GENERAL_STATUS = "GENERAL_STATUS"
    UNKNOWN = "UNKNOWN"


class ClarificationOption(BaseModel):
    """Selectable option presented to the user when resolving an ambiguous contextual request."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str
    entity_type: str  # "goal" | "task" | "milestone" | "memory"
    entity_id: str
    description: str | None = None


class ClarificationPrompt(BaseModel):
    """Context clarification prompt emitted when request ambiguity is high."""

    model_config = ConfigDict(from_attributes=True)

    clarification_type: str  # "AMBIGUOUS_GOAL" | "AMBIGUOUS_TASK" | "AMBIGUOUS_MILESTONE" | "AMBIGUOUS_MEMORY"
    prompt_message: str
    original_intent: str
    original_slots: dict[str, Any] = Field(default_factory=dict)
    options: list[ClarificationOption] = Field(default_factory=list)


class ChatMessageRole(StrEnum):
    """Role classification for conversational messages."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    """Discrete message within an agent conversation session."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: ChatMessageRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    intent: AgentIntent | None = None
    card_type: str | None = None
    card_data: dict[str, Any] | None = None
    run_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None


class AgentSession(BaseModel):
    """Stateful agent session tracking context, active goal, current task, milestone, memory, and history."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: uuid.UUID
    active_goal_id: uuid.UUID | None = None
    active_goal_title: str | None = None
    current_task_id: uuid.UUID | None = None
    current_task_title: str | None = None
    active_milestone_id: uuid.UUID | None = None
    active_milestone_title: str | None = None
    last_referenced_memory_id: uuid.UUID | None = None
    pending_clarification: ClarificationPrompt | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    context_state: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatRequest(BaseModel):
    """Payload sent by the conversational interface."""

    model_config = ConfigDict(from_attributes=True)

    message: str = Field(..., min_length=1, max_length=2000, description="User conversational utterance")
    session_id: str | None = Field(default=None, description="Existing session ID if continuing a thread")
    active_goal_id: uuid.UUID | None = Field(default=None, description="Explicit active goal override")
    current_task_id: uuid.UUID | None = Field(default=None, description="Explicit current task override")


class ChatResponse(BaseModel):
    """Structured response from the Agent Orchestrator."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    message: ChatMessage
    intent: AgentIntent
    active_goal_id: uuid.UUID | None = None
    active_goal_title: str | None = None
    current_task_id: uuid.UUID | None = None
    current_task_title: str | None = None
    active_milestone_id: uuid.UUID | None = None
    active_milestone_title: str | None = None
    last_referenced_memory_id: uuid.UUID | None = None
    clarification_prompt: ClarificationPrompt | None = None
    run_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    state_updates: dict[str, Any] = Field(default_factory=dict)
    card_type: str | None = None
    card_data: dict[str, Any] | None = None
    suggested_replies: list[str] = Field(default_factory=list)


class ConversationContextSummary(BaseModel):
    """Active conversational context summary for the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    user_id: uuid.UUID
    user_name: str
    active_goal_id: uuid.UUID | None = None
    active_goal_title: str | None = None
    active_goal_status: str | None = None
    current_task_id: uuid.UUID | None = None
    current_task_title: str | None = None
    current_task_priority: str | None = None
    active_milestone_id: uuid.UUID | None = None
    active_milestone_title: str | None = None
    last_referenced_memory_id: uuid.UUID | None = None
    pending_clarification: ClarificationPrompt | None = None
    active_goals_count: int = 0
    total_memories_count: int = 0
    learned_weaknesses_count: int = 0
    preferences_count: int = 0
    recent_intents: list[str] = Field(default_factory=list)
