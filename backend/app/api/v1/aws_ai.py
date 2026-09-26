import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.services.aws.agent_core import (
    AgentCoreActionRequest,
    AgentCoreResponse,
    get_agent_core_provider,
)
from app.services.aws.config import AWSConfigManager
from app.services.aws.cost_tracker import CostMetricsSummary, cost_tracker
from app.services.aws.strands import (
    StrandItem,
    StrandSearchResult,
    get_strands_provider,
)

logger = logging.getLogger("lifethread.api.aws_ai")

router = APIRouter(prefix="/aws", tags=["AWS AI Integration"])


class AWSStatusResponse(BaseModel):
    """Response payload for AWS AI integration status and configuration inspection."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    region: str
    has_credentials: bool
    access_key_masked: str
    role_arn: str
    default_model: str
    fast_model: str
    timeout_seconds: float
    max_retries: int
    fallback_enabled: bool
    agent_id_configured: bool
    knowledge_base_id_configured: bool


class InvokeAgentCorePayload(BaseModel):
    """Payload to invoke AgentCore action execution."""

    action_group: str = Field(..., description="Action group or skill category name")
    action_name: str = Field(..., description="Specific skill or action name (e.g. goal_management, planning, memory, evaluation, replanning)")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Action arguments")
    session_id: str | None = Field(default=None, description="Optional conversational session ID")
    goal_id: uuid.UUID | None = Field(default=None, description="Optional goal ID context")


class IndexStrandPayload(BaseModel):
    """Payload to index a semantic context strand."""

    title: str
    content: str
    category: str = Field(default="general", description="goal_context, weakness, preference, reflection")
    goal_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchStrandsPayload(BaseModel):
    """Payload to query context strands."""

    query: str
    goal_id: uuid.UUID | None = None
    limit: int = Field(default=5, ge=1, le=50)
    min_score: float = Field(default=0.4, ge=0.0, le=1.0)


@router.get("/status", response_model=AWSStatusResponse)
async def get_aws_status(
    current_user: User = Depends(get_current_active_user),
) -> AWSStatusResponse:
    """Inspect AWS AI configuration, active Bedrock models, and client security posture."""
    masked = AWSConfigManager.get_masked_credentials()
    return AWSStatusResponse(
        status="operational" if masked["has_credentials"] else "fallback_mode",
        **masked,
    )


@router.get("/costs", response_model=CostMetricsSummary)
async def get_cost_metrics(
    current_user: User = Depends(get_current_active_user),
) -> CostMetricsSummary:
    """Retrieve real-time token accounting and estimated USD expenditures for Bedrock invocations."""
    return cost_tracker.get_summary()


@router.post("/agent-core/invoke", response_model=AgentCoreResponse)
async def invoke_agent_core(
    payload: InvokeAgentCorePayload,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AgentCoreResponse:
    """Execute a structured action group through the AgentCore provider abstraction."""
    provider = get_agent_core_provider()
    session_id = payload.session_id or str(uuid.uuid4())

    request = AgentCoreActionRequest(
        action_group=payload.action_group,
        action_name=payload.action_name,
        parameters=payload.parameters,
        session_id=session_id,
        user_id=current_user.id,
        goal_id=payload.goal_id,
    )

    return await provider.execute_action(
        request=request,
        db=db,
        user_permissions=["*"],
    )


@router.post("/strands/index", response_model=dict[str, str])
async def index_strand(
    payload: IndexStrandPayload,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Index an item into semantic context strands."""
    provider = get_strands_provider()
    item = StrandItem(
        user_id=current_user.id,
        goal_id=payload.goal_id,
        title=payload.title,
        content=payload.content,
        category=payload.category,
        metadata=payload.metadata,
    )
    strand_id = await provider.index(item, db=db)
    return {"strand_id": strand_id, "message": "Strand indexed successfully"}


@router.post("/strands/search", response_model=list[StrandSearchResult])
async def search_strands(
    payload: SearchStrandsPayload,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[StrandSearchResult]:
    """Search relevant context strands isolated to the authenticated user."""
    provider = get_strands_provider()
    return await provider.search(
        query=payload.query,
        user_id=current_user.id,
        goal_id=payload.goal_id,
        limit=payload.limit,
        min_score=payload.min_score,
        db=db,
    )
