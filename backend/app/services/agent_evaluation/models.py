import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvaluationPillar(StrEnum):
    """The 10 evaluation pillars required by Module 39 for automated testing."""

    GOAL_UNDERSTANDING = "goal_understanding"
    GOAL_DECOMPOSITION = "goal_decomposition"
    PLANNING = "planning"
    MEMORY_RETRIEVAL = "memory_retrieval"
    TOOL_SELECTION = "tool_selection"
    CONSTRAINT_HANDLING = "constraint_handling"
    REPLANNING = "replanning"
    FAILURE_RECOVERY = "failure_recovery"
    PERMISSION_ENFORCEMENT = "permission_enforcement"
    PROMPT_INJECTION_RESISTANCE = "prompt_injection_resistance"


class ScenarioEvaluationResult(BaseModel):
    """Execution outcome of a scenario evaluation test capturing observable behavior."""

    model_config = ConfigDict(from_attributes=True)

    scenario_id: str
    name: str
    pillar: EvaluationPillar
    input: dict[str, Any] = Field(default_factory=dict)
    expected_behavior: str
    actual_behavior: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0, description="Normalized score between 0.0 and 1.0")
    duration_ms: float = 0.0
    evaluation_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Safe execution metadata, timings, and checks (no hidden CoT)",
    )


class AgentEvaluationReport(BaseModel):
    """Comprehensive test report produced after automated suite execution."""

    model_config = ConfigDict(from_attributes=True)

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float
    total_scenarios: int
    passed_count: int
    failed_count: int
    pass_rate: float
    pillar_scores: dict[str, float] = Field(default_factory=dict)
    scenarios: list[ScenarioEvaluationResult] = Field(default_factory=list)
    summary_markdown: str = ""
