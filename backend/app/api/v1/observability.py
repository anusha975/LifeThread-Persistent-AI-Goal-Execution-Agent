from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.services.observability.models import (
    AgentObservabilityDashboard,
    AlertType,
    DiagnosticRunTelemetry,
    ObservabilityAlert,
    ToolObservabilitySummary,
)
from app.services.observability.service import AgentObservabilityService

router = APIRouter(prefix="/observability", tags=["Agent Observability"])


@router.get(
    "/dashboard",
    response_model=AgentObservabilityDashboard,
    summary="Agent Observability Dashboard",
    description="Retrieve comprehensive real-time telemetry across agent, LLM, MCP, tools, memory, replanning, and active alerts.",
)
async def get_observability_dashboard(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentObservabilityDashboard:
    """Compile and return the full observability dashboard for system operators."""
    return await AgentObservabilityService.get_dashboard(db=db)


@router.get(
    "/metrics",
    summary="Agent Observability Metrics Summary",
    description="Retrieve high-level telemetry metrics summary including token usage, latencies, and tool failure rates.",
)
async def get_observability_metrics(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Retrieve summarized operational metrics for monitoring integrations."""
    dash = await AgentObservabilityService.get_dashboard(db=db)
    return {
        "system_status": dash.system_status,
        "overall_tool_failure_rate": dash.overall_tool_failure_rate,
        "total_retries": dash.total_retries,
        "agent_latency_avg_ms": dash.agent_latency.avg_ms,
        "llm_latency_avg_ms": dash.llm_latency.avg_ms,
        "mcp_latency_avg_ms": dash.mcp_latency.avg_ms,
        "tool_latency_avg_ms": dash.tool_latency.avg_ms,
        "memory_latency_avg_ms": dash.memory_latency.avg_ms,
        "token_usage": dash.token_usage,
        "replanning_count": dash.replanning_metrics.get("total_count", 0),
        "goal_progress_summary": dash.goal_progress_summary,
        "memory_retrieval_summary": dash.memory_retrieval_summary,
        "active_alert_count": len(dash.active_alerts),
    }


@router.get(
    "/latency",
    summary="Latency Breakdown by Category",
    description="Retrieve statistical percentiles (p50, p90, p95, p99) for Agent, LLM, MCP, Tool, and Memory operations.",
)
async def get_latency_breakdown(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Retrieve statistical latency percentiles for operational SLA tracking."""
    dash = await AgentObservabilityService.get_dashboard(db=db)
    return {
        "agent": dash.agent_latency.model_dump(),
        "llm": dash.llm_latency.model_dump(),
        "mcp": dash.mcp_latency.model_dump(),
        "tool": dash.tool_latency.model_dump(),
        "memory": dash.memory_latency.model_dump(),
    }


@router.get(
    "/tools",
    response_model=list[ToolObservabilitySummary],
    summary="Tool Metrics and Failure Rates",
    description="Retrieve per-tool operational telemetry including execution counts, failure rates, and retry totals.",
)
async def get_tool_metrics(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ToolObservabilitySummary]:
    """Retrieve operational telemetry across all internal and MCP tools."""
    dash = await AgentObservabilityService.get_dashboard(db=db)
    return dash.tool_metrics


@router.get(
    "/alerts",
    response_model=list[ObservabilityAlert],
    summary="List Operational Alerts",
    description="Retrieve system alerts for repeated tool failure, unusually long runs, repeated replanning, or database errors.",
)
async def list_observability_alerts(
    current_user: Annotated[User, Depends(get_current_active_user)],
    resolved: Annotated[bool | None, Query(description="Filter by resolved status")] = None,
    alert_type: Annotated[AlertType | None, Query(description="Filter by alert type")] = None,
) -> list[ObservabilityAlert]:
    """Retrieve active and historical operational alarms."""
    return AgentObservabilityService.get_alerts(resolved=resolved, alert_type=alert_type)


@router.post(
    "/alerts/{alert_id}/resolve",
    summary="Resolve Operational Alert",
    description="Mark an active observability alarm as resolved by an operator.",
)
async def resolve_observability_alert(
    alert_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Resolve an operational alert."""
    success = AgentObservabilityService.resolve_alert(alert_id=alert_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert '{alert_id}' not found",
        )
    return {"alert_id": alert_id, "resolved": True}


@router.get(
    "/diagnostics/{run_id}",
    response_model=DiagnosticRunTelemetry,
    summary="Diagnose Agent Failure from Telemetry",
    description="Pinpoint the exact cause, failing stage, and root cause of an agent failure directly from execution telemetry.",
)
async def diagnose_agent_run(
    run_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DiagnosticRunTelemetry:
    """Diagnose agent run failure from telemetry with actionable operator recommendations."""
    return await AgentObservabilityService.diagnose_run(run_id=run_id, db=db)
