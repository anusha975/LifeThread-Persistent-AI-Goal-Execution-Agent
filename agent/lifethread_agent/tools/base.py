import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ToolPermissionLevel(IntEnum):
    """Hierarchical permission level required to execute a tool.

    Lower integer value = less privileged / safer.
    READ_ONLY (1) <= STANDARD (2) <= SENSITIVE (3) <= ADMIN (4)
    """

    READ_ONLY = 1
    STANDARD = 2
    SENSITIVE = 3
    ADMIN = 4


class RetryPolicy(BaseModel):
    """Configuration for automatic retry attempts on transient tool failures."""

    max_retries: int = Field(default=0, ge=0, description="Maximum number of retry attempts")
    initial_delay_seconds: float = Field(
        default=0.1, ge=0.0, description="Initial delay before first retry"
    )
    backoff_factor: float = Field(
        default=2.0, ge=1.0, description="Multiplier applied to delay after each retry"
    )
    retryable_error_types: list[str] = Field(
        default_factory=lambda: [
            "TimeoutError",
            "TransientError",
            "ConnectionError",
            "NetworkError",
        ],
        description="Names of exception types eligible for automatic retry",
    )


class ToolErrorCode(StrEnum):
    """Categorized taxonomy of tool execution error conditions."""

    VALIDATION_ERROR = "validation_error"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT_ERROR = "timeout_error"
    EXECUTION_FAILED = "execution_failed"
    TOOL_NOT_FOUND = "tool_not_found"
    CANCELLED = "cancelled"
    MALICIOUS_ARGUMENTS = "malicious_arguments"


class ToolError(Exception):
    """Normalized exception representing tool failure with structured classification."""

    def __init__(
        self,
        code: ToolErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        recoverable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.recoverable = recoverable

    def to_dict(self) -> dict[str, Any]:
        """Convert error representation to serializable dictionary."""
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable,
        }


class ToolCall(BaseModel):
    """Structured request to execute a specific tool with validated arguments."""

    call_id: str = Field(
        default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}",
        description="Globally unique identifier for this tool call",
    )
    tool_name: str = Field(..., description="Name of the tool to invoke")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Raw or parsed arguments to supply to tool handler"
    )
    caller_permission_level: ToolPermissionLevel = Field(
        default=ToolPermissionLevel.STANDARD,
        description="Permission level granted to the executing caller",
    )
    context: dict[str, Any] = Field(
        default_factory=dict, description="Execution context passed from the runtime"
    )


class ToolResult(BaseModel):
    """Comprehensive outcome of a tool execution attempt."""

    call_id: str = Field(..., description="Correlating tool call identifier")
    tool_name: str = Field(..., description="Name of the executed tool")
    success: bool = Field(..., description="Whether the tool succeeded without error")
    data: Any = Field(default=None, description="Validated output data returned by tool")
    error: dict[str, Any] | None = Field(
        default=None, description="Normalized error details if execution failed"
    )
    execution_time_ms: float = Field(
        default=0.0, ge=0.0, description="Execution duration in milliseconds"
    )
    retries_attempted: int = Field(
        default=0, ge=0, description="Number of retry attempts performed"
    )
    executed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when execution completed",
    )


class ToolDefinition(BaseModel):
    """Complete specification of a registered tool."""

    name: str = Field(..., description="Unique tool identifier, e.g. 'calculate_schedule'")
    description: str = Field(..., description="Human-readable description of what tool performs")
    input_schema: type[BaseModel] | dict[str, Any] = Field(
        ..., description="Pydantic model or schema definition defining expected arguments"
    )
    output_schema: type[BaseModel] | dict[str, Any] | None = Field(
        default=None, description="Optional Pydantic model for output validation"
    )
    permission_level: ToolPermissionLevel = Field(
        default=ToolPermissionLevel.STANDARD,
        description="Minimum permission level required to invoke this tool",
    )
    timeout: float = Field(default=30.0, ge=0.1, description="Per-execution timeout in seconds")
    retry_policy: RetryPolicy = Field(
        default_factory=RetryPolicy, description="Retry configuration for transient failures"
    )
    handler: Callable[..., Coroutine[Any, Any, Any]] | None = Field(
        default=None, description="Async callable handler executing the tool logic"
    )

    model_config = {"arbitrary_types_allowed": True}
