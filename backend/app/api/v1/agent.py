import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.services.agent_trace.models import (
    AgentRun,
    AgentRunSummary,
    EventStatus,
    ReconstructedAgentTrace,
)
from app.services.agent_trace.service import AgentTraceService
from app.services.orchestrator.models import (
    AgentSession,
    ChatRequest,
    ChatResponse,
    ConversationContextSummary,
)

router = APIRouter(prefix="/agent", tags=["Agent Activity Center"])


@router.get(
    "/runs",
    response_model=list[AgentRunSummary],
    summary="List Agent Execution Runs",
    description="Retrieve historical agent execution runs with high-level summaries and triggers.",
)
async def list_agent_runs(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    goal_id: Annotated[uuid.UUID | None, Query(description="Filter by associated goal ID")] = None,
    correlation_id: Annotated[str | None, Query(description="Filter by correlation ID")] = None,
    status_filter: Annotated[
        EventStatus | None, Query(alias="status", description="Filter by run status")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum runs to return")] = 50,
) -> list[AgentRunSummary]:
    """Retrieve agent execution runs belonging to the authenticated user."""
    return await AgentTraceService.list_runs(
        db=db,
        user_id=current_user.id,
        goal_id=goal_id,
        status=status_filter,
        correlation_id=correlation_id,
        limit=limit,
    )


@router.get(
    "/runs/{run_id}",
    response_model=AgentRun,
    summary="Get Agent Execution Run & Trace",
    description="Retrieve the complete execution trace for a run: Agent Run → Decision → Tool Call → Tool Result → Evaluation → State Update.",
)
async def get_agent_run(
    run_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRun:
    """Retrieve discrete execution events for a specific agent run ensuring tenant isolation."""
    run = await AgentTraceService.get_run(db=db, run_id=run_id, user_id=current_user.id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AgentRun '{run_id}' not found",
        )
    return run


@router.get(
    "/traces",
    response_model=list[AgentRunSummary],
    summary="List Agent Traces",
    description="Retrieve execution traces for agent runs with trace_id, correlation_id, and metadata.",
)
async def list_agent_traces(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    goal_id: Annotated[uuid.UUID | None, Query(description="Filter by associated goal ID")] = None,
    correlation_id: Annotated[str | None, Query(description="Filter by correlation ID")] = None,
    status_filter: Annotated[
        EventStatus | None, Query(alias="status", description="Filter by run status")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum traces to return")] = 50,
) -> list[AgentRunSummary]:
    """Retrieve agent traces belonging to the authenticated user."""
    return await AgentTraceService.list_runs(
        db=db,
        user_id=current_user.id,
        goal_id=goal_id,
        status=status_filter,
        correlation_id=correlation_id,
        limit=limit,
    )


@router.get(
    "/traces/{trace_id}",
    response_model=AgentRun,
    summary="Get Agent Execution Trace",
    description="Retrieve the execution run and event trace for a specific trace ID.",
)
async def get_agent_trace(
    trace_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRun:
    """Retrieve execution trace for a specific trace ID ensuring tenant isolation."""
    run = await AgentTraceService.get_run(db=db, run_id=trace_id, user_id=current_user.id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent trace '{trace_id}' not found",
        )
    return run


@router.get(
    "/traces/{trace_id}/reconstruct",
    response_model=ReconstructedAgentTrace,
    summary="Reconstruct Agent Run from Execution Trace",
    description="Reconstruct any agent run from its complete 10-stage execution trace without exposing private model reasoning.",
)
async def reconstruct_agent_trace(
    trace_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReconstructedAgentTrace:
    """Reconstruct an agent run across all 10 execution stages."""
    reconstruction = await AgentTraceService.reconstruct_trace(
        db=db,
        trace_id=trace_id,
        user_id=current_user.id,
    )
    if not reconstruction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent trace '{trace_id}' not found or cannot be reconstructed",
        )
    return reconstruction


# =============================================================================
# Conversational Agent Interface Endpoints
# =============================================================================


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Conversational Agent Interface",
    description="Execute natural-language commands connected to real LifeThread state and the Agent Orchestrator.",
)
async def chat_with_agent(
    request: ChatRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatResponse:
    """Execute a conversational command and return stateful response, diffs, cards, and traces."""
    from app.services.orchestrator.service import AgentOrchestrator

    return await AgentOrchestrator.process_chat(
        db=db,
        user_id=current_user.id,
        request=request,
    )


@router.get(
    "/chat/context",
    response_model=ConversationContextSummary,
    summary="Get Conversational Context Summary",
    description="Retrieve the active user context, active goal, current task, and memory statistics.",
)
async def get_chat_context(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    session_id: Annotated[str | None, Query(description="Current session identifier")] = None,
) -> ConversationContextSummary:
    """Retrieve active session context summary for the authenticated user."""
    from app.services.orchestrator.service import AgentOrchestrator

    user_name = current_user.display_name or current_user.email or "LifeThread User"
    return await AgentOrchestrator.get_context_summary(
        db=db,
        user_id=current_user.id,
        user_name=user_name,
        session_id=session_id,
    )


@router.get(
    "/chat/sessions/{session_id}",
    response_model=AgentSession,
    summary="Get Agent Conversation Session",
    description="Retrieve message history and state for a specific conversation session.",
)
async def get_chat_session(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AgentSession:
    """Retrieve stateful agent conversation session ensuring tenant isolation."""
    from app.services.orchestrator.service import AgentOrchestrator

    session = AgentOrchestrator.get_or_create_session(
        user_id=current_user.id,
        session_id=session_id,
    )
    if session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return session


# =============================================================================
# Agent Skills Layer Endpoints (Module 34)
# =============================================================================


@router.get(
    "/skills",
    summary="List Discovered Agent Skills",
    description="Discover all available reusable agent skills with purpose, required permissions, tools, and failure behavior.",
)
async def list_agent_skills(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Discover all registered domain agent skills."""
    from app.services.skills.registry import SkillRegistry

    return SkillRegistry.list_skill_metadata()


@router.get(
    "/skills/{skill_name}",
    summary="Get Agent Skill Specification",
    description="Inspect a specific skill's purpose, schemas, permissions, tools, and failure behavior.",
)
async def get_agent_skill(
    skill_name: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retrieve metadata and contract schemas for a specific agent skill."""
    from app.services.skills.registry import SkillRegistry

    skill = SkillRegistry.get_skill(skill_name)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent skill '{skill_name}' not found",
        )
    return skill.get_metadata()


@router.post(
    "/skills/{skill_name}/execute",
    summary="Execute Agent Skill",
    description="Invoke an agent skill directly with input validation, permission enforcement, and execution tracing.",
)
async def execute_agent_skill(
    skill_name: str,
    inputs: dict[str, Any],
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    goal_id: Annotated[uuid.UUID | None, Query(description="Optional associated goal context")] = None,
    session_id: Annotated[str | None, Query(description="Optional session context")] = None,
):
    """Execute a single agent skill independently with tracing and failure behavior."""
    from app.services.skills.models import SkillExecutionContext
    from app.services.skills.registry import SkillRegistry

    context = SkillExecutionContext(
        user_id=current_user.id,
        db=db,
        session_id=session_id,
        goal_id=goal_id,
        user_permissions={"*"},
    )
    return await SkillRegistry.execute_skill(
        skill_name=skill_name,
        context=context,
        inputs=inputs,
    )


@router.post(
    "/skills/pipeline",
    summary="Execute Composable Skill Pipeline",
    description="Execute a sequential chain of composable skills passing outputs to subsequent steps.",
)
async def execute_skill_pipeline(
    request: dict[str, Any],
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Execute a composable pipeline of multiple agent skills."""
    from app.services.skills.models import SkillExecutionContext, SkillPipelineRequest
    from app.services.skills.registry import SkillRegistry

    pipeline_req = SkillPipelineRequest.model_validate(request)
    context = SkillExecutionContext(
        user_id=current_user.id,
        db=db,
        goal_id=pipeline_req.goal_id,
        user_permissions={"*"},
    )
    return await SkillRegistry.execute_pipeline(
        request=pipeline_req,
        context=context,
    )


