import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class RecoveryErrorCode(StrEnum):
    """Categorical structured error codes for failure recovery."""

    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_MALFORMED_RESPONSE = "LLM_MALFORMED_RESPONSE"
    MCP_TIMEOUT = "MCP_TIMEOUT"
    MCP_UNAVAILABLE = "MCP_UNAVAILABLE"
    TOOL_EXECUTION_FAILURE = "TOOL_EXECUTION_FAILURE"
    DB_TRANSIENT_FAILURE = "DB_TRANSIENT_FAILURE"
    INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
    PLANNING_FAILURE = "PLANNING_FAILURE"
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"
    RETRIES_EXHAUSTED = "RETRIES_EXHAUSTED"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    RECOVERY_FAILED = "RECOVERY_FAILED"


class FailureCategory(StrEnum):
    """Classification of failure nature determining recovery strategy."""

    TRANSIENT = "TRANSIENT"  # Can retry with backoff (e.g. network timeout, DB lock)
    SYNTACTIC = "SYNTACTIC"  # Can repair/validate (e.g. malformed JSON, invalid args)
    CAPACITY = "CAPACITY"  # Can compress/prune (e.g. context overflow)
    LOGICAL = "LOGICAL"  # Can rollback/fallback (e.g. planning cycle, infeasible plan)
    PERMANENT = "PERMANENT"  # Fast-fail without retry loop


class RetryPolicy(BaseModel):
    """Bounded retry policy configuration with exponential backoff and jitter."""

    model_config = ConfigDict(frozen=True)

    max_retries: int = Field(
        default=3, ge=0, le=10, description="Strict upper bound on retry attempts"
    )
    base_delay_seconds: float = Field(default=0.05, ge=0.0, description="Initial delay in seconds")
    max_delay_seconds: float = Field(
        default=1.0, ge=0.0, description="Maximum ceiling delay in seconds"
    )
    backoff_factor: float = Field(default=2.0, ge=1.0, description="Exponential backoff multiplier")
    jitter: bool = Field(
        default=True, description="Add randomized jitter to avoid thundering herds"
    )


class UserNotification(BaseModel):
    """Structured user-facing notification describing recovery action or degraded state."""

    model_config = ConfigDict(from_attributes=True)

    notification_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str
    user_id: uuid.UUID
    severity: str = Field(default="WARNING", description="Severity: INFO, WARNING, ERROR, CRITICAL")
    title: str
    message: str
    remediation_action: str | None = None
    dismissed: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FailureEvent(BaseModel):
    """Audit telemetry event recording a detected failure."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str
    error_code: RecoveryErrorCode
    category: FailureCategory
    message: str
    original_exception: str | None = None
    attempt_number: int = 1
    context_data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RecoveryAction(BaseModel):
    """Telemetry item recording an executed recovery action step."""

    action_type: str = Field(description="Action: RETRY, FALLBACK, ROLLBACK, SAFE_FAILURE")
    attempt: int
    delay_seconds: float = 0.0
    details: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RecoveryResult(BaseModel, Generic[T]):  # noqa: UP046
    """Standardized result returned by the failure recovery engine."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    correlation_id: str
    success: bool
    data: T | None = None
    final_action: str = Field(
        default="EXECUTED",
        description="Outcome: EXECUTED, RECOVERED_VIA_RETRY, RECOVERED_VIA_FALLBACK, SAFE_FAILURE",
    )
    attempts_made: int = 1
    fallback_applied: bool = False
    rollback_applied: bool = False
    error_code: RecoveryErrorCode | None = None
    error_message: str | None = None
    user_notification: UserNotification | None = None
    state_preserved: bool = True
    actions_taken: list[RecoveryAction] = Field(default_factory=list)
