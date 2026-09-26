import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.services.learning import (
    AgentLearningLoopEngine,
    ExecutionOutcome,
    LearningPlanningResult,
    OutcomeEvaluation,
)

router = APIRouter(prefix="/learning", tags=["Agent Learning Loop"])


class OutcomeSubmissionResponse(BaseModel):
    outcome_id: str
    evaluation: OutcomeEvaluation
    memory_created: bool
    memory_id: uuid.UUID | None = None
    memory_content: str | None = None
    memory_type: str | None = None
    confidence: float
    importance_score: float
    is_factual: bool
    is_hypothesis: bool


class ApplyLearningRequest(BaseModel):
    goal_id: uuid.UUID = Field(description="Goal ID to adapt using past learnings")
    commit: bool = Field(default=True, description="Whether to commit task adaptations to DB")


@router.post(
    "/outcome",
    response_model=OutcomeSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit execution outcome and execute learning loop",
)
async def submit_execution_outcome(
    outcome: ExecutionOutcome,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OutcomeSubmissionResponse:
    """Ingest task or agent action execution result, evaluate against benchmarks,

    and update/persist persistent memory.
    """
    # Enforce tenant isolation
    outcome.user_id = current_user.id

    evaluation, memory = await AgentLearningLoopEngine.record_and_learn(
        db=db,
        outcome=outcome,
    )

    return OutcomeSubmissionResponse(
        outcome_id=outcome.outcome_id,
        evaluation=evaluation,
        memory_created=memory is not None,
        memory_id=memory.id if memory else None,
        memory_content=memory.content if memory else None,
        memory_type=memory.memory_type.value if memory else None,
        confidence=memory.confidence if memory else evaluation.confidence,
        importance_score=memory.importance_score if memory else evaluation.importance_score,
        is_factual=evaluation.is_factual,
        is_hypothesis=evaluation.is_hypothesis,
    )


@router.get(
    "/memories",
    summary="Retrieve active learning memories",
)
async def get_learning_memories(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    domain: Annotated[str | None, Query(description="Optional domain filter")] = None,
    topic: Annotated[str | None, Query(description="Optional topic filter")] = None,
    goal_id: Annotated[uuid.UUID | None, Query(description="Optional goal ID filter")] = None,
    task_id: Annotated[uuid.UUID | None, Query(description="Optional task ID filter")] = None,
    min_confidence: Annotated[
        float, Query(ge=0.0, le=1.0, description="Minimum confidence filter")
    ] = 0.0,
) -> list[dict[str, Any]]:
    """Retrieve learning memories recorded by the Agent Learning Loop for the authenticated user."""
    memories = await AgentLearningLoopEngine.get_learning_memories(
        db=db,
        user_id=current_user.id,
        goal_id=goal_id,
        task_id=task_id,
        domain=domain,
        topic=topic,
        min_confidence=min_confidence,
    )

    return [
        {
            "id": str(m.id),
            "content": m.content,
            "memory_type": m.memory_type.value,
            "confidence": m.confidence,
            "importance_score": m.importance_score,
            "status": m.status.value,
            "access_count": m.access_count,
            "created_at": m.created_at.isoformat(),
            "metadata": m.metadata_json,
        }
        for m in memories
    ]


@router.post(
    "/apply-to-plan",
    response_model=LearningPlanningResult,
    summary="Apply user learnings to adapt a goal plan",
)
async def apply_learnings_to_plan(
    request: ApplyLearningRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LearningPlanningResult:
    """Future Planner: Inspects past learning memories and adapts goal tasks and duration."""
    return await AgentLearningLoopEngine.apply_learnings_to_planner(
        db=db,
        user_id=current_user.id,
        goal_id=request.goal_id,
        commit=request.commit,
    )
