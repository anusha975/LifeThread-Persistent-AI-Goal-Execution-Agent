from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.goal import GoalPriority


class GoalConstraintDraft(BaseModel):
    """Structured constraint extracted from user input without hallucinated limits."""

    type: str = Field(
        ..., min_length=1, max_length=100, description="Constraint type (e.g. time, budget, tech)"
    )
    value: str = Field(..., min_length=1, description="Explicit rule or limit stated by the user")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Structured parameters")

    model_config = ConfigDict(from_attributes=True)


class GoalMilestoneDraft(BaseModel):
    """Optional milestone suggestion identified during understanding."""

    title: str = Field(..., min_length=1, max_length=255, description="Milestone title")
    description: str | None = Field(default=None, description="Deliverable description")
    deadline: datetime | None = Field(default=None, description="Milestone target deadline in UTC")

    model_config = ConfigDict(from_attributes=True)


class GoalStructuredSpecification(BaseModel):
    """Structured goal specification extracted from natural language."""

    title: str = Field(
        ..., min_length=3, max_length=255, description="Concise, meaningful goal title"
    )
    objective: str = Field(..., min_length=5, description="Clear target objective statement")
    description: str | None = Field(default=None, description="Elaborated context or background")
    deadline: datetime | None = Field(default=None, description="Normalized target deadline in UTC")
    priority: str = Field(
        default="medium", description="Goal execution priority (low, medium, high, critical)"
    )
    constraints: list[GoalConstraintDraft] = Field(
        default_factory=list,
        description="Explicit constraints extracted from user input (never fabricated)",
    )
    success_criteria: list[str] = Field(
        default_factory=list,
        description="Measurable acceptance criteria to confirm completion",
    )
    milestones: list[GoalMilestoneDraft] = Field(
        default_factory=list,
        description="Optional initial phase milestones",
    )

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v: Any) -> str:
        """Normalize priority strings to lowercase canonical form."""
        if isinstance(v, GoalPriority):
            return v.value.lower()
        if isinstance(v, str):
            val = v.strip().lower()
            valid = {"low", "medium", "high", "critical"}
            if val in valid:
                return val
        return "medium"

    model_config = ConfigDict(from_attributes=True)


class AmbiguityReport(BaseModel):
    """Assessment of goal ambiguity and missing critical information."""

    is_ambiguous: bool = Field(
        default=False, description="Whether the goal statement is overly vague or underspecified"
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="List of critical missing details required for execution planning",
    )
    clarification_questions: list[str] = Field(
        default_factory=list,
        description="Targeted questions for the user to resolve ambiguity",
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Understanding confidence metric (0.0 to 1.0)",
    )


class GoalUnderstandRequest(BaseModel):
    """Input payload to analyze and understand a natural language goal."""

    text: str = Field(
        ...,
        min_length=3,
        max_length=4000,
        description="Natural language statement of the goal (e.g. 'I need to become interview-ready for an AI Engineer role in 10 days.')",
        examples=["I need to become interview-ready for an AI Engineer role in 10 days."],
    )
    timezone: str | None = Field(
        default=None,
        description="User timezone (e.g. 'America/New_York', 'Asia/Kolkata'). Defaults to authenticated user's timezone.",
    )
    reference_time: datetime | None = Field(
        default=None,
        description="Optional reference datetime for deterministic testing and relative date parsing.",
    )
    clarification_answers: dict[str, str] | None = Field(
        default=None,
        description="Optional answers to previously generated clarification questions.",
    )


class GoalUnderstandingSchema(BaseModel):
    """Complete validated result of the Goal Understanding Engine.

    Stores the raw user request separately from the structured interpretation,
    while providing direct top-level access to core goal attributes.
    """

    raw_request: str = Field(
        ...,
        description="Exact raw natural language request provided by the user, preserved separately from interpretation",
    )
    objective: str = Field(..., description="Target objective statement")
    title: str = Field(..., description="Meaningful title generated for the goal")
    description: str | None = Field(default=None, description="Optional background description")
    deadline: datetime | None = Field(default=None, description="Target deadline normalized to UTC")
    priority: str = Field(
        default="medium", description="Priority level (low, medium, high, critical)"
    )
    constraints: list[GoalConstraintDraft] = Field(
        default_factory=list,
        description="Validated constraints (never invented)",
    )
    success_criteria: list[str] = Field(
        default_factory=list,
        description="Measurable success criteria",
    )
    milestones: list[GoalMilestoneDraft] = Field(
        default_factory=list,
        description="Initial phase milestones",
    )

    # Ambiguity detection & clarification
    is_ambiguous: bool = Field(default=False, description="Whether ambiguity was detected")
    missing_information: list[str] = Field(
        default_factory=list,
        description="Identified missing information",
    )
    clarification_questions: list[str] = Field(
        default_factory=list,
        description="Clarification questions if missing information or ambiguity detected",
    )
    needs_clarification: bool = Field(
        default=False,
        description="True if user should answer clarification questions before finalizing the goal",
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score",
    )

    # Separate structured interpretation object
    structured_interpretation: GoalStructuredSpecification = Field(
        ...,
        description="Isolated structured goal specification container",
    )

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v: Any) -> str:
        """Normalize priority strings to lowercase canonical form."""
        if isinstance(v, GoalPriority):
            return v.value.lower()
        if isinstance(v, str):
            val = v.strip().lower()
            valid = {"low", "medium", "high", "critical"}
            if val in valid:
                return val
        return "medium"

    model_config = ConfigDict(from_attributes=True)
