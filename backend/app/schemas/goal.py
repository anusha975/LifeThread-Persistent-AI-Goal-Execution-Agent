import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.goal import GoalPriority, GoalStatus, MilestoneStatus


class GoalConstraintCreate(BaseModel):
    """Payload to attach a constraint to a goal."""

    type: str = Field(
        ..., min_length=1, max_length=100, description="Constraint type (e.g. time, budget, policy)"
    )
    value: str = Field(..., min_length=1, description="Constraint limit or rule")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional constraint metadata"
    )


class GoalConstraintResponse(BaseModel):
    """Public representation of a goal constraint."""

    id: uuid.UUID
    goal_id: uuid.UUID
    type: str
    value: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class GoalMilestoneCreate(BaseModel):
    """Payload to define an initial milestone for a goal."""

    title: str = Field(..., min_length=1, max_length=255, description="Milestone title")
    description: str | None = Field(default=None, description="Optional milestone description")
    status: MilestoneStatus = Field(
        default=MilestoneStatus.PENDING, description="Initial milestone status"
    )
    order_index: int = Field(default=0, ge=0, description="Sequence order of milestone")
    deadline: datetime | None = Field(default=None, description="Target completion deadline")


class GoalMilestoneResponse(BaseModel):
    """Public representation of a goal milestone."""

    id: uuid.UUID
    goal_id: uuid.UUID
    title: str
    description: str | None
    status: MilestoneStatus
    order_index: int
    deadline: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GoalCreate(BaseModel):
    """Payload to create a new user goal."""

    title: str = Field(..., min_length=3, max_length=255, description="Goal title")
    objective: str = Field(..., min_length=5, description="Target objective or mission")
    description: str | None = Field(default=None, description="Detailed context or description")
    priority: GoalPriority = Field(default=GoalPriority.MEDIUM, description="Goal priority")
    deadline: datetime | None = Field(default=None, description="Target deadline in UTC")
    success_criteria: list[str] = Field(
        default_factory=list, description="List of measurable success criteria"
    )
    constraints: list[GoalConstraintCreate] = Field(
        default_factory=list, description="Initial constraints"
    )
    milestones: list[GoalMilestoneCreate] = Field(
        default_factory=list, description="Initial phase milestones"
    )

    @field_validator("title")
    @classmethod
    def validate_meaningful_title(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 3:
            raise ValueError("Goal title must contain at least 3 non-whitespace characters")
        return stripped

    @field_validator("deadline")
    @classmethod
    def validate_deadline_not_past(cls, v: datetime | None) -> datetime | None:
        if v is not None:
            # Normalize to UTC comparison
            now = datetime.now(UTC)
            v_utc = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
            # Allow up to 10 minutes past to tolerate client clock skew
            if v_utc < (now - timedelta(minutes=10)):
                raise ValueError("Goal deadline cannot be set in the past")
        return v

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v: Any) -> Any:
        if isinstance(v, str):
            val = v.strip().upper()
            if hasattr(GoalPriority, val):
                return GoalPriority(val)
        return v


class GoalUpdate(BaseModel):
    """Payload for partial updates to a goal."""

    title: str | None = Field(default=None, min_length=3, max_length=255)
    objective: str | None = Field(default=None, min_length=5)
    description: str | None = None
    priority: GoalPriority | None = None
    deadline: datetime | None = None
    success_criteria: list[str] | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 3:
                raise ValueError("Goal title must contain at least 3 non-whitespace characters")
            return stripped
        return v

    @field_validator("deadline")
    @classmethod
    def validate_deadline_not_past(cls, v: datetime | None) -> datetime | None:
        if v is not None:
            now = datetime.now(UTC)
            v_utc = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
            if v_utc < (now - timedelta(minutes=10)):
                raise ValueError("Goal deadline cannot be set in the past")
        return v

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v: Any) -> Any:
        if v is not None and isinstance(v, str):
            val = v.strip().upper()
            if hasattr(GoalPriority, val):
                return GoalPriority(val)
        return v


class GoalResponse(BaseModel):
    """Full structured public representation of a goal."""

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    objective: str
    description: str | None
    status: GoalStatus
    priority: GoalPriority
    deadline: datetime | None
    success_criteria: list[str]
    created_at: datetime
    updated_at: datetime
    constraints: list[GoalConstraintResponse] = Field(default_factory=list)
    milestones: list[GoalMilestoneResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class GoalListResponse(BaseModel):
    """Paginated collection of goals."""

    items: list[GoalResponse]
    total: int
    limit: int
    offset: int
