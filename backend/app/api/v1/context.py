import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.services.context_engine import (
    BuiltContext,
    ContextBudget,
    ContextBuilder,
    ContextSource,
)

router = APIRouter(prefix="/context", tags=["Context Engine"])


class BuildContextRequest(BaseModel):
    """Request payload to assemble an intelligent, token-bounded context for an agent."""

    query: str | None = Field(
        default=None,
        description="Current user prompt or agent query to score relevance against",
    )
    task_id: uuid.UUID | None = Field(
        default=None,
        description="Active task ID for high-priority task context",
    )
    goal_id: uuid.UUID | None = Field(
        default=None,
        description="Active goal ID for goal state and constraints context",
    )
    total_tokens: int = Field(
        default=4000,
        ge=100,
        le=32000,
        description="Total token budget limit",
    )
    min_relevance_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score threshold for candidate inclusion",
    )
    reserved_tokens_per_source: dict[ContextSource, int] = Field(
        default_factory=dict,
        description="Optional reserved token guarantees per source category",
    )
    max_tokens_per_source: dict[ContextSource, int] = Field(
        default_factory=dict,
        description="Optional maximum token limits per source category",
    )
    conversation_history: list[dict[str, Any]] | None = Field(
        default=None,
        description="Recent conversation turns (role, content, timestamp)",
    )
    historical_events: list[dict[str, Any]] | None = Field(
        default=None,
        description="Recent historical milestone or execution events",
    )


@router.post(
    "/build",
    response_model=BuiltContext,
    status_code=status.HTTP_200_OK,
    summary="Build prioritized, token-bounded context for an agent",
)
async def build_context(
    request: BuildContextRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BuiltContext:
    """Assembles agent context adhering strictly to Context Priority (1-7), token budget, and user isolation."""
    budget = ContextBudget(
        total_tokens=request.total_tokens,
        min_relevance_threshold=request.min_relevance_threshold,
        reserved_tokens_per_source=request.reserved_tokens_per_source,
        max_tokens_per_source=request.max_tokens_per_source,
    )

    # Validate goal ownership if goal_id provided (fail-closed IDOR defense)
    if request.goal_id:
        from app.services.goal import GoalService
        await GoalService.get_goal_by_id(db=db, goal_id=request.goal_id, user_id=current_user.id)

    # Inspect query for prompt injection if provided
    clean_query = request.query
    if clean_query:
        from app.core.prompt_guard import PromptGuard
        _, clean_query = PromptGuard.inspect_and_defend(
            text=clean_query,
            user_id=str(current_user.id),
            action="BUILD_CONTEXT_QUERY",
        )

    builder = ContextBuilder(default_budget=budget)
    return await builder.build_from_domain(
        db=db,
        user_id=current_user.id,
        task_id=request.task_id,
        goal_id=request.goal_id,
        query=clean_query,
        conversation_history=request.conversation_history,
        historical_events=request.historical_events,
        budget=budget,
    )
