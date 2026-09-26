import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from app.core.exceptions import LifeThreadException
from app.schemas.evaluation import (
    GoalProgressEvaluation,
    GoalRiskEvaluation,
    GoalWeaknessesEvaluation,
    TaskEvaluation,
)
from app.services.evaluation import EvaluationService
from fastapi import HTTPException
from lifethread_agent.tools import ToolPermissionLevel, ToolRegistry
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("lifethread.mcp.tools.evaluation")


# ============================================================================
# INPUT SCHEMAS FOR EVALUATION MCP TOOLS
# ============================================================================


class EvaluateProgressToolInput(BaseModel):
    """Input payload to evaluate overall goal progress and deadline risk."""

    goal_id: uuid.UUID = Field(..., description="Unique UUID of the target goal to evaluate")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated goal owner")


class EvaluateTaskToolInput(BaseModel):
    """Input payload to evaluate an individual task's health and prerequisites."""

    task_id: uuid.UUID = Field(..., description="Unique UUID of the task to evaluate")
    user_id: uuid.UUID = Field(
        ..., description="UUID of the authenticated user requesting the evaluation"
    )


class IdentifyWeaknessToolInput(BaseModel):
    """Input payload to detect bottlenecks, overdue tasks, and plan vulnerabilities."""

    goal_id: uuid.UUID = Field(..., description="Unique UUID of the target goal")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated goal owner")


class CalculateGoalRiskToolInput(BaseModel):
    """Input payload to calculate multivariate risk scores across schedule, dependencies, and priority."""

    goal_id: uuid.UUID = Field(..., description="Unique UUID of the target goal")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated goal owner")


# ============================================================================
# HELPER: RESOLVE DB SESSION
# ============================================================================


@asynccontextmanager
async def _resolve_db_session(context: dict[str, Any] | None) -> AsyncGenerator[AsyncSession, None]:
    """Provide an AsyncSession from execution context or a fresh transaction context."""
    if context and "db" in context:
        yield context["db"]
    else:
        from app.db.session import transaction_context

        async with transaction_context() as session:
            yield session


# ============================================================================
# TOOL REGISTRATION
# ============================================================================


def register_evaluation_mcp_tools(registry: ToolRegistry) -> None:
    """Register all 4 Evaluation MCP tools into the given registry."""

    # 1. EVALUATE PROGRESS
    @registry.tool(
        name="evaluate_progress",
        description="Evaluate goal progress considering task completion, priority weights, remaining workload, and deadline risk.",
        input_schema=EvaluateProgressToolInput,
        output_schema=GoalProgressEvaluation,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def evaluate_progress(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "MCP Tool [evaluate_progress] invoked for goal [%s] by user [%s]",
            goal_id,
            user_id,
        )
        async with _resolve_db_session(context) as session:
            try:
                evaluation = await EvaluationService.evaluate_progress(
                    db=session,
                    goal_id=goal_id,
                    user_id=user_id,
                )
                return evaluation.model_dump(mode="json")
            except HTTPException as exc:
                logger.warning("MCP [evaluate_progress] HTTPException: %s", exc.detail)
                raise LifeThreadException(
                    message=str(exc.detail),
                    code="NOT_FOUND" if exc.status_code == 404 else "EVALUATION_ERROR",
                    status_code=exc.status_code,
                ) from exc

    # 2. EVALUATE TASK
    @registry.tool(
        name="evaluate_task",
        description="Evaluate an individual task's status, uncompleted prerequisites, critical path membership, and overdue state.",
        input_schema=EvaluateTaskToolInput,
        output_schema=TaskEvaluation,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def evaluate_task(
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "MCP Tool [evaluate_task] invoked for task [%s] by user [%s]",
            task_id,
            user_id,
        )
        async with _resolve_db_session(context) as session:
            try:
                evaluation = await EvaluationService.evaluate_task(
                    db=session,
                    task_id=task_id,
                    user_id=user_id,
                )
                return evaluation.model_dump(mode="json")
            except HTTPException as exc:
                logger.warning("MCP [evaluate_task] HTTPException: %s", exc.detail)
                raise LifeThreadException(
                    message=str(exc.detail),
                    code="NOT_FOUND" if exc.status_code == 404 else "EVALUATION_ERROR",
                    status_code=exc.status_code,
                ) from exc

    # 3. IDENTIFY WEAKNESS
    @registry.tool(
        name="identify_weakness",
        description="Identify plan bottlenecks, blocked tasks, recent execution failures, and overdue tasks.",
        input_schema=IdentifyWeaknessToolInput,
        output_schema=GoalWeaknessesEvaluation,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def identify_weakness(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "MCP Tool [identify_weakness] invoked for goal [%s] by user [%s]",
            goal_id,
            user_id,
        )
        async with _resolve_db_session(context) as session:
            try:
                evaluation = await EvaluationService.identify_weakness(
                    db=session,
                    goal_id=goal_id,
                    user_id=user_id,
                )
                return evaluation.model_dump(mode="json")
            except HTTPException as exc:
                logger.warning("MCP [identify_weakness] HTTPException: %s", exc.detail)
                raise LifeThreadException(
                    message=str(exc.detail),
                    code="NOT_FOUND" if exc.status_code == 404 else "EVALUATION_ERROR",
                    status_code=exc.status_code,
                ) from exc

    # 4. CALCULATE GOAL RISK
    @registry.tool(
        name="calculate_goal_risk",
        description="Calculate multivariate goal risk considering schedule, dependency blockers, and high-priority exposure.",
        input_schema=CalculateGoalRiskToolInput,
        output_schema=GoalRiskEvaluation,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def calculate_goal_risk(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "MCP Tool [calculate_goal_risk] invoked for goal [%s] by user [%s]",
            goal_id,
            user_id,
        )
        async with _resolve_db_session(context) as session:
            try:
                evaluation = await EvaluationService.calculate_goal_risk(
                    db=session,
                    goal_id=goal_id,
                    user_id=user_id,
                )
                return evaluation.model_dump(mode="json")
            except HTTPException as exc:
                logger.warning("MCP [calculate_goal_risk] HTTPException: %s", exc.detail)
                raise LifeThreadException(
                    message=str(exc.detail),
                    code="NOT_FOUND" if exc.status_code == 404 else "EVALUATION_ERROR",
                    status_code=exc.status_code,
                ) from exc
