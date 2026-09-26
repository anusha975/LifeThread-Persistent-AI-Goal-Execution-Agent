import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MetricCategory(StrEnum):
    """Categorization of observability latency and operational metrics."""

    AGENT_RUN = "agent_run"
    LLM = "llm"
    MCP = "mcp"
    TOOL = "tool"
    MEMORY = "memory"
    REPLANNING = "replanning"
    DATABASE = "database"
    GOAL = "goal"


class AlertSeverity(StrEnum):
    """Severity classification for observability alerts."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertType(StrEnum):
    """The 4 required alarm classes for Module 38."""

    REPEATED_TOOL_FAILURE = "REPEATED_TOOL_FAILURE"
    UNUSUALLY_LONG_RUN = "UNUSUALLY_LONG_RUN"
    REPEATED_REPLANNING = "REPEATED_REPLANNING"
    DATABASE_FAILURE = "DATABASE_FAILURE"


class LatencyMetric(BaseModel):
    """Granular latency record for agent operations, LLM, MCP, tools, or DB."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: MetricCategory
    name: str
    duration_ms: float
    success: bool = True
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolMetric(BaseModel):
    """Execution telemetry for internal tools and MCP tool servers."""

    model_config = ConfigDict(from_attributes=True)

    tool_name: str
    is_mcp: bool = False
    duration_ms: float
    success: bool
    error_type: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    run_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TokenUsageMetric(BaseModel):
    """Telemetry capturing token consumption across foundation models."""

    model_config = ConfigDict(from_attributes=True)

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    run_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryRetrievalMetric(BaseModel):
    """Telemetry measuring memory recall latency, returned items, and relevance."""

    model_config = ConfigDict(from_attributes=True)

    query: str | None = None
    duration_ms: float
    item_count: int
    avg_confidence: float = 1.0
    run_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReplanningMetric(BaseModel):
    """Telemetry tracking replanning triggers and plan version increments."""

    model_config = ConfigDict(from_attributes=True)

    goal_id: uuid.UUID | None = None
    reason: str
    previous_version: int
    new_version: int
    run_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GoalProgressMetric(BaseModel):
    """Snapshot telemetry of user goal progress and execution health."""

    model_config = ConfigDict(from_attributes=True)

    goal_id: uuid.UUID
    goal_title: str
    progress_percentage: float
    status: str
    is_overdue: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ObservabilityAlert(BaseModel):
    """Operational alert raised when telemetry thresholds are violated."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    source: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved: bool = False
    resolved_at: datetime | None = None


class LatencyPercentiles(BaseModel):
    """Statistical percentile summary of latency measurements."""

    count: int = 0
    avg_ms: float = 0.0
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0


class ToolObservabilitySummary(BaseModel):
    """Aggregated operational health per tool."""

    tool_name: str
    is_mcp: bool = False
    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0
    failure_rate: float = 0.0
    avg_duration_ms: float = 0.0
    retry_count: int = 0
    last_error: str | None = None


class AgentObservabilityDashboard(BaseModel):
    """Comprehensive observability dashboard payload for system operators."""

    model_config = ConfigDict(from_attributes=True)

    system_status: str = "HEALTHY"
    agent_latency: LatencyPercentiles
    llm_latency: LatencyPercentiles
    mcp_latency: LatencyPercentiles
    tool_latency: LatencyPercentiles
    memory_latency: LatencyPercentiles
    tool_metrics: list[ToolObservabilitySummary] = Field(default_factory=list)
    overall_tool_failure_rate: float = 0.0
    total_retries: int = 0
    token_usage: dict[str, Any] = Field(default_factory=dict)
    replanning_metrics: dict[str, Any] = Field(default_factory=dict)
    goal_progress_summary: dict[str, Any] = Field(default_factory=dict)
    memory_retrieval_summary: dict[str, Any] = Field(default_factory=dict)
    active_alerts: list[ObservabilityAlert] = Field(default_factory=list)
    alert_counts_by_type: dict[str, int] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DiagnosticRunTelemetry(BaseModel):
    """Deep root-cause diagnostic telemetry for an individual agent run."""

    model_config = ConfigDict(from_attributes=True)

    run_id: str
    trace_id: str | None = None
    correlation_id: str | None = None
    status: str
    duration_ms: int | None = None
    is_failure: bool
    failure_category: str | None = None
    failure_root_cause: str | None = None
    failing_stage: str | None = None
    failing_tool: str | None = None
    error_details: dict[str, Any] = Field(default_factory=dict)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    operator_recommendations: list[str] = Field(default_factory=list)
