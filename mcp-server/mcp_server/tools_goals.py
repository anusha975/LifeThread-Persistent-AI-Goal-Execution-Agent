import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.models.goal import GoalPriority, GoalStatus
from app.schemas.goal import (
    GoalConstraintCreate,
    GoalConstraintResponse,
    GoalCreate,
    GoalMilestoneCreate,
    GoalMilestoneResponse,
    GoalUpdate,
)
from app.services.goal import GoalService
from fastapi import HTTPException
from lifethread_agent.tools import ToolPermissionLevel, ToolRegistry
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger("lifethread.mcp.tools.goals")


# ============================================================================
# PRECISE INPUT & OUTPUT SCHEMAS
# ============================================================================


class GoalToolOutput(BaseModel):
    """Structured output representation returned by all Goal MCP tools."""

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


class CreateGoalToolInput(BaseModel):
    """Input payload to create a new user goal via MCP."""

    user_id: uuid.UUID = Field(..., description="Unique UUID of the authenticated goal owner")
    title: str = Field(..., min_length=3, max_length=255, description="Goal title")
    objective: str = Field(
        ..., min_length=5, description="High-level objective or mission statement"
    )
    description: str | None = Field(
        default=None, description="Optional detailed context or description"
    )
    priority: GoalPriority = Field(
        default=GoalPriority.MEDIUM, description="Priority level of the goal"
    )
    deadline: datetime | None = Field(default=None, description="Target completion deadline in UTC")
    success_criteria: list[str] = Field(
        default_factory=list, description="Measurable success metrics"
    )
    constraints: list[GoalConstraintCreate] = Field(
        default_factory=list, description="Initial goal constraints"
    )
    milestones: list[GoalMilestoneCreate] = Field(
        default_factory=list, description="Initial phased milestones"
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 3:
            raise ValueError("Goal title must contain at least 3 non-whitespace characters")
        return stripped

    @field_validator("deadline")
    @classmethod
    def validate_deadline_not_past(cls, v: datetime | None) -> datetime | None:
        if v is not None:
            now = datetime.now(UTC)
            v_utc = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
            if v_utc < (now - timedelta(minutes=10)):
                raise ValueError("Goal deadline cannot be set in the past")
        return v


class GetGoalToolInput(BaseModel):
    """Input payload to retrieve an existing goal by ID."""

    goal_id: uuid.UUID = Field(..., description="UUID of the target goal")
    user_id: uuid.UUID = Field(
        ..., description="UUID of the authenticated user requesting the goal"
    )


class UpdateGoalToolInput(BaseModel):
    """Input payload to update an existing goal."""

    goal_id: uuid.UUID = Field(..., description="UUID of the goal to update")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated goal owner")
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


class GoalActionToolInput(BaseModel):
    """Input payload for lifecycle actions on a goal (pause, resume, complete)."""

    goal_id: uuid.UUID = Field(..., description="UUID of the target goal")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated goal owner")


# ============================================================================
# DATABASE SESSION RESOLVER
# ============================================================================


@asynccontextmanager
async def _resolve_db_session(context: dict[str, Any] | None):
    """Resolve an AsyncSession from execution context or standard transaction manager."""
    if context and "db" in context:
        yield context["db"]
    else:
        from app.db.session import transaction_context

        async with transaction_context() as session:
            yield session


# ============================================================================
# TOOL REGISTRATION
# ============================================================================


def register_goal_mcp_tools(registry: ToolRegistry) -> None:
    """Register all 6 Goal Engine MCP tools into the given registry."""

    # 1. CREATE GOAL
    @registry.tool(
        name="create_goal",
        description="Create a new goal with title, objective, constraints, and milestones for an authenticated user.",
        input_schema=CreateGoalToolInput,
        output_schema=GoalToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def create_goal(
        user_id: uuid.UUID,
        title: str,
        objective: str,
        description: str | None = None,
        priority: GoalPriority = GoalPriority.MEDIUM,
        deadline: datetime | None = None,
        success_criteria: list[str] | None = None,
        constraints: list[dict[str, Any]] | None = None,
        milestones: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"MCP Tool [create_goal] invoked by user [{user_id}] for title: {title}")
        parsed_constraints = [GoalConstraintCreate.model_validate(c) for c in (constraints or [])]
        parsed_milestones = [GoalMilestoneCreate.model_validate(m) for m in (milestones or [])]

        goal_in = GoalCreate(
            title=title,
            objective=objective,
            description=description,
            priority=priority,
            deadline=deadline,
            success_criteria=success_criteria or [],
            constraints=parsed_constraints,
            milestones=parsed_milestones,
        )

        async with _resolve_db_session(context) as session:
            goal = await GoalService.create_goal(
                db=session,
                user_id=user_id,
                goal_in=goal_in,
            )
            logger.info(f"MCP Tool [create_goal] created goal [{goal.id}] for user [{user_id}]")
            return GoalToolOutput.model_validate(goal).model_dump(mode="json")

    # 2. GET GOAL
    @registry.tool(
        name="get_goal",
        description="Retrieve goal details by goal_id ensuring strict authenticated user ownership.",
        input_schema=GetGoalToolInput,
        output_schema=GoalToolOutput,
        permission_level=ToolPermissionLevel.READ_ONLY,
    )
    async def get_goal(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"MCP Tool [get_goal] query for goal [{goal_id}] by user [{user_id}]")
        async with _resolve_db_session(context) as session:
            try:
                goal = await GoalService.get_goal_by_id(
                    db=session,
                    goal_id=goal_id,
                    user_id=user_id,
                )
            except HTTPException as exc:
                logger.warning(f"MCP Tool [get_goal] access denied or not found: {exc.detail}")
                raise ValueError(f"Goal '{goal_id}' not found or access denied.") from exc

            return GoalToolOutput.model_validate(goal).model_dump(mode="json")

    # 3. UPDATE GOAL
    @registry.tool(
        name="update_goal",
        description="Update fields on an existing goal belonging to the authenticated user.",
        input_schema=UpdateGoalToolInput,
        output_schema=GoalToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def update_goal(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str | None = None,
        objective: str | None = None,
        description: str | None = None,
        priority: GoalPriority | None = None,
        deadline: datetime | None = None,
        success_criteria: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"MCP Tool [update_goal] updating goal [{goal_id}] by user [{user_id}]")
        update_fields: dict[str, Any] = {}
        if title is not None:
            update_fields["title"] = title
        if objective is not None:
            update_fields["objective"] = objective
        if description is not None:
            update_fields["description"] = description
        if priority is not None:
            update_fields["priority"] = priority
        if deadline is not None:
            update_fields["deadline"] = deadline
        if success_criteria is not None:
            update_fields["success_criteria"] = success_criteria

        goal_update = GoalUpdate(**update_fields)

        async with _resolve_db_session(context) as session:
            try:
                goal = await GoalService.get_goal_by_id(
                    db=session, goal_id=goal_id, user_id=user_id
                )
                updated_goal = await GoalService.update_goal(
                    db=session,
                    goal=goal,
                    goal_in=goal_update,
                )
            except HTTPException as exc:
                raise ValueError(f"Goal '{goal_id}' update failed: {exc.detail}") from exc

            logger.info(f"MCP Tool [update_goal] successfully updated goal [{goal_id}]")
            return GoalToolOutput.model_validate(updated_goal).model_dump(mode="json")

    # 4. PAUSE GOAL
    @registry.tool(
        name="pause_goal",
        description="Pause an active goal belonging to the authenticated user.",
        input_schema=GoalActionToolInput,
        output_schema=GoalToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def pause_goal(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"MCP Tool [pause_goal] pausing goal [{goal_id}] by user [{user_id}]")
        async with _resolve_db_session(context) as session:
            try:
                goal = await GoalService.get_goal_by_id(
                    db=session, goal_id=goal_id, user_id=user_id
                )
                paused_goal = await GoalService.pause_goal(db=session, goal=goal)
            except HTTPException as exc:
                raise ValueError(f"Cannot pause goal '{goal_id}': {exc.detail}") from exc

            return GoalToolOutput.model_validate(paused_goal).model_dump(mode="json")

    # 5. RESUME GOAL
    @registry.tool(
        name="resume_goal",
        description="Resume a paused or draft goal back to ACTIVE status.",
        input_schema=GoalActionToolInput,
        output_schema=GoalToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def resume_goal(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"MCP Tool [resume_goal] resuming goal [{goal_id}] by user [{user_id}]")
        async with _resolve_db_session(context) as session:
            try:
                goal = await GoalService.get_goal_by_id(
                    db=session, goal_id=goal_id, user_id=user_id
                )
                resumed_goal = await GoalService.resume_goal(db=session, goal=goal)
            except HTTPException as exc:
                raise ValueError(f"Cannot resume goal '{goal_id}': {exc.detail}") from exc

            return GoalToolOutput.model_validate(resumed_goal).model_dump(mode="json")

    # 6. COMPLETE GOAL
    @registry.tool(
        name="complete_goal",
        description="Transition an active or paused goal to COMPLETED status.",
        input_schema=GoalActionToolInput,
        output_schema=GoalToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def complete_goal(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"MCP Tool [complete_goal] completing goal [{goal_id}] by user [{user_id}]")
        async with _resolve_db_session(context) as session:
            try:
                goal = await GoalService.get_goal_by_id(
                    db=session, goal_id=goal_id, user_id=user_id
                )
                completed_goal = await GoalService.complete_goal(db=session, goal=goal)
            except HTTPException as exc:
                raise ValueError(f"Cannot complete goal '{goal_id}': {exc.detail}") from exc

            return GoalToolOutput.model_validate(completed_goal).model_dump(mode="json")
