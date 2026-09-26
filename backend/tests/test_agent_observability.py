import uuid

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.middleware.security import get_rate_limiter
from app.services.agent_trace.models import EventStatus, ExecutionEventType
from app.services.agent_trace.service import AgentTraceService
from app.services.observability.models import (
    AlertSeverity,
    AlertType,
)
from app.services.observability.service import AgentObservabilityService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def reset_state():
    """Reset rate limiter and observability telemetry state between tests."""
    get_rate_limiter().reset()
    AgentObservabilityService.reset()
    yield
    get_rate_limiter().reset()
    AgentObservabilityService.reset()


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"observability_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashedpass",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_client(test_user: User, session_factory):
    token, _, _ = create_access_token(subject=str(test_user.id))

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


# =============================================================================
# 1. Latency & Execution Metrics Tracking Tests
# =============================================================================


def test_percentile_calculation():
    """Verify statistical percentiles calculation (p50, p90, p95, p99, avg)."""
    durations = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    pct = AgentObservabilityService.calculate_percentiles(durations)

    assert pct.count == 10
    assert pct.avg_ms == 55.0
    assert pct.min_ms == 10.0
    assert pct.max_ms == 100.0
    assert pct.p50_ms == 55.0
    assert pct.p90_ms == 91.0
    assert pct.p95_ms == 95.5
    assert pct.p99_ms == 99.1


def test_empty_percentiles():
    """Empty measurements yield zeroed percentiles without division by zero."""
    pct = AgentObservabilityService.calculate_percentiles([])
    assert pct.count == 0
    assert pct.avg_ms == 0.0


@pytest.mark.asyncio
async def test_track_agent_and_llm_and_mcp_latency():
    """Verify tracking of agent latency, LLM latency, MCP latency, and token usage."""
    # 1. Record Agent runs
    AgentObservabilityService.record_agent_run("run-1", 120.0, EventStatus.SUCCESS)
    AgentObservabilityService.record_agent_run("run-2", 340.0, EventStatus.SUCCESS)

    # 2. Record LLM calls & token usage
    AgentObservabilityService.record_llm_call(
        duration_ms=450.0,
        prompt_tokens=250,
        completion_tokens=75,
        model="bedrock:anthropic.claude-3-haiku",
        run_id="run-1",
    )
    AgentObservabilityService.record_llm_call(
        duration_ms=820.0,
        prompt_tokens=500,
        completion_tokens=150,
        model="bedrock:anthropic.claude-3-sonnet",
        run_id="run-2",
    )

    # 3. Record MCP calls
    AgentObservabilityService.record_mcp_call("mcp:vector_search", 85.0, success=True, retry_count=1)
    AgentObservabilityService.record_mcp_call("mcp:vector_search", 92.0, success=True, retry_count=0)

    # 4. Record memory retrieval
    AgentObservabilityService.record_memory_retrieval(
        duration_ms=25.0,
        item_count=5,
        avg_confidence=0.92,
        query="user preferences",
    )

    dash = await AgentObservabilityService.get_dashboard()
    assert dash.agent_latency.count == 2
    assert dash.agent_latency.avg_ms == 230.0

    assert dash.llm_latency.count == 2
    assert dash.llm_latency.avg_ms == 635.0

    assert dash.token_usage["total_tokens"] == (325 + 650)
    assert dash.token_usage["prompt_tokens"] == 750
    assert dash.token_usage["completion_tokens"] == 225

    assert dash.mcp_latency.count == 2
    assert dash.mcp_latency.avg_ms == 88.5

    assert dash.memory_retrieval_summary["total_retrievals"] == 1
    assert dash.memory_retrieval_summary["avg_latency_ms"] == 25.0
    assert dash.memory_retrieval_summary["avg_confidence"] == 0.92


# =============================================================================
# 2. Tool Metrics, Failure Rates & Retry Count Tests
# =============================================================================


@pytest.mark.asyncio
async def test_tool_failure_rate_and_retries():
    """Verify tool failure rate computation, call counts, and retry tracking."""
    # Tool A: 3 calls, 1 fail, 2 retries
    AgentObservabilityService.record_tool_call("tool_a", 50.0, success=True, retry_count=1)
    AgentObservabilityService.record_tool_call("tool_a", 40.0, success=False, error="Timeout", retry_count=1)
    AgentObservabilityService.record_tool_call("tool_a", 45.0, success=True, retry_count=0)

    # Tool B: 2 calls, 0 fail
    AgentObservabilityService.record_tool_call("tool_b", 20.0, success=True, retry_count=0)
    AgentObservabilityService.record_tool_call("tool_b", 25.0, success=True, retry_count=0)

    dash = await AgentObservabilityService.get_dashboard()
    assert dash.total_retries == 2

    # Overall tool failure rate: 1 failure out of 5 calls = 20.0%
    assert dash.overall_tool_failure_rate == 20.0

    summary_a = next(t for t in dash.tool_metrics if t.tool_name == "tool_a")
    assert summary_a.total_calls == 3
    assert summary_a.failure_count == 1
    assert summary_a.failure_rate == 33.33
    assert summary_a.retry_count == 2


# =============================================================================
# 3. Operational Alerts Tests (All 4 Alarm Categories)
# =============================================================================


def test_alert_repeated_tool_failure():
    """Alert Trigger 1: Repeated tool failure triggers REPEATED_TOOL_FAILURE alarm."""
    tool_name = "failing_weather_api"

    # 1st and 2nd failure: below threshold
    AgentObservabilityService.record_tool_call(tool_name, 50.0, success=False, error="503 Service Unavailable")
    AgentObservabilityService.record_tool_call(tool_name, 55.0, success=False, error="503 Service Unavailable")
    assert len(AgentObservabilityService.get_alerts(alert_type=AlertType.REPEATED_TOOL_FAILURE)) == 0

    # 3rd failure: hits threshold
    AgentObservabilityService.record_tool_call(tool_name, 60.0, success=False, error="503 Service Unavailable")
    alerts = AgentObservabilityService.get_alerts(alert_type=AlertType.REPEATED_TOOL_FAILURE)
    assert len(alerts) == 1
    assert alerts[0].alert_type == AlertType.REPEATED_TOOL_FAILURE
    assert alerts[0].source == f"tool:{tool_name}"
    assert "consecutive failures" in alerts[0].title


def test_alert_unusually_long_agent_run():
    """Alert Trigger 2: Unusually long agent runs triggers UNUSUALLY_LONG_RUN alarm."""
    # Under threshold (<10,000ms)
    AgentObservabilityService.record_agent_run("run-fast", 2500.0, EventStatus.SUCCESS)
    assert len(AgentObservabilityService.get_alerts(alert_type=AlertType.UNUSUALLY_LONG_RUN)) == 0

    # Over threshold (14,500ms)
    AgentObservabilityService.record_agent_run("run-slow", 14500.0, EventStatus.SUCCESS)
    alerts = AgentObservabilityService.get_alerts(alert_type=AlertType.UNUSUALLY_LONG_RUN)
    assert len(alerts) == 1
    assert alerts[0].alert_type == AlertType.UNUSUALLY_LONG_RUN
    assert alerts[0].source == "run:run-slow"
    assert alerts[0].details["duration_ms"] == 14500.0


def test_alert_repeated_replanning():
    """Alert Trigger 3: Repeated replanning on a goal triggers REPEATED_REPLANNING alarm."""
    goal_id = uuid.uuid4()

    # 1st and 2nd replan: below threshold
    AgentObservabilityService.record_replanning(goal_id, reason="SCHEDULE_CONFLICT", previous_version=1, new_version=2)
    AgentObservabilityService.record_replanning(goal_id, reason="AVAILABLE_TIME_CHANGED", previous_version=2, new_version=3)
    assert len(AgentObservabilityService.get_alerts(alert_type=AlertType.REPEATED_REPLANNING)) == 0

    # 3rd replan: hits threshold
    AgentObservabilityService.record_replanning(goal_id, reason="DEADLINE_MOVED", previous_version=3, new_version=4)
    alerts = AgentObservabilityService.get_alerts(alert_type=AlertType.REPEATED_REPLANNING)
    assert len(alerts) == 1
    assert alerts[0].alert_type == AlertType.REPEATED_REPLANNING
    assert alerts[0].source == f"goal:{str(goal_id)}"
    assert alerts[0].details["replan_count_in_window"] == 3


def test_alert_database_failures():
    """Alert Trigger 4: Database operational errors triggers DATABASE_FAILURE alarm."""
    # 1st failure: below threshold
    AgentObservabilityService.record_database_operation("commit", 120.0, success=False, error="OperationalError: database locked")
    assert len(AgentObservabilityService.get_alerts(alert_type=AlertType.DATABASE_FAILURE)) == 0

    # 2nd failure: hits threshold
    AgentObservabilityService.record_database_operation("select", 95.0, success=False, error="OperationalError: disk I/O error")
    alerts = AgentObservabilityService.get_alerts(alert_type=AlertType.DATABASE_FAILURE)
    assert len(alerts) == 1
    assert alerts[0].alert_type == AlertType.DATABASE_FAILURE
    assert alerts[0].severity == AlertSeverity.CRITICAL
    assert alerts[0].source == "database"


def test_resolve_alert():
    """Verify resolving active alerts."""
    alert = AgentObservabilityService.raise_alert(
        alert_type=AlertType.UNUSUALLY_LONG_RUN,
        severity=AlertSeverity.WARNING,
        title="Test Alert",
        message="Test alert message",
        source="run:123",
    )
    assert not alert.resolved

    success = AgentObservabilityService.resolve_alert(alert.id)
    assert success is True
    assert alert.resolved is True
    assert alert.resolved_at is not None

    # Filter by resolved status
    unresolved = AgentObservabilityService.get_alerts(resolved=False)
    assert len(unresolved) == 0


# =============================================================================
# 4. Acceptance Criteria: Operator Failure Diagnosis from Telemetry
# =============================================================================


@pytest.mark.asyncio
async def test_diagnose_tool_failure_from_telemetry():
    """Acceptance Criteria: System operators can identify the cause of an agent failure from telemetry.

    Case A: Tool execution failure.
    """
    user_id = uuid.uuid4()
    run = AgentTraceService.start_run(
        user_id=user_id,
        trigger="TEST_TOOL_FAIL",
        summary="Run failing on external tool",
    )

    AgentTraceService.record_event(
        run_id=run.id,
        user_id=user_id,
        event_type=ExecutionEventType.TOOL_CALL,
        status=EventStatus.SUCCESS,
        short_explanation="Invoked remote currency conversion tool.",
        tool_name="convert_currency",
    )

    AgentTraceService.record_event(
        run_id=run.id,
        user_id=user_id,
        event_type=ExecutionEventType.TOOL_RESULT,
        status=EventStatus.FAILED,
        short_explanation="Tool 'convert_currency' failed: Connection timed out to remote gateway.",
        tool_name="convert_currency",
    )

    AgentTraceService.finish_run(run.id, user_id, status=EventStatus.FAILED)

    diagnostic = await AgentObservabilityService.diagnose_run(run.id)
    assert diagnostic.is_failure is True
    assert diagnostic.failure_category == "TOOL_EXECUTION_FAILURE"
    assert diagnostic.failing_tool == "convert_currency"
    assert "Connection timed out" in str(diagnostic.failure_root_cause)
    assert len(diagnostic.operator_recommendations) >= 1
    assert any("convert_currency" in r for r in diagnostic.operator_recommendations)


@pytest.mark.asyncio
async def test_diagnose_database_failure_from_telemetry():
    """Acceptance Criteria: System operators can identify the cause of an agent failure from telemetry.

    Case B: Database error.
    """
    user_id = uuid.uuid4()
    run = AgentTraceService.start_run(
        user_id=user_id,
        trigger="TEST_DB_FAIL",
        summary="Run failing on database transaction",
    )

    AgentTraceService.record_event(
        run_id=run.id,
        user_id=user_id,
        event_type=ExecutionEventType.STATE_UPDATE,
        status=EventStatus.FAILED,
        short_explanation="Database transaction failed: SQLite database locked during commit.",
    )

    AgentTraceService.finish_run(run.id, user_id, status=EventStatus.FAILED)

    diagnostic = await AgentObservabilityService.diagnose_run(run.id)
    assert diagnostic.is_failure is True
    assert diagnostic.failure_category == "DATABASE_ERROR"
    assert "SQLite database locked" in str(diagnostic.failure_root_cause)
    assert any("connection pool" in r.lower() for r in diagnostic.operator_recommendations)


# =============================================================================
# 5. REST API Endpoints Tests
# =============================================================================


@pytest.mark.asyncio
async def test_api_dashboard_endpoint(auth_client: AsyncClient):
    """Verify GET /api/v1/observability/dashboard returns complete dashboard payload."""
    AgentObservabilityService.record_agent_run("run-api", 210.0, EventStatus.SUCCESS)
    AgentObservabilityService.record_llm_call(350.0, 100, 50, "test-model")
    AgentObservabilityService.record_tool_call("test_tool", 45.0, success=True)

    res = await auth_client.get("/api/v1/observability/dashboard")
    assert res.status_code == 200
    data = res.json()

    assert data["system_status"] in ("HEALTHY", "DEGRADED", "CRITICAL")
    assert "agent_latency" in data
    assert "llm_latency" in data
    assert "mcp_latency" in data
    assert "tool_latency" in data
    assert "memory_latency" in data
    assert "tool_metrics" in data
    assert "token_usage" in data
    assert "replanning_metrics" in data
    assert "goal_progress_summary" in data
    assert "memory_retrieval_summary" in data
    assert "active_alerts" in data


@pytest.mark.asyncio
async def test_api_metrics_and_latency_endpoints(auth_client: AsyncClient):
    """Verify GET /api/v1/observability/metrics and /latency."""
    AgentObservabilityService.record_agent_run("run-api-2", 300.0)

    res_metrics = await auth_client.get("/api/v1/observability/metrics")
    assert res_metrics.status_code == 200
    metrics_data = res_metrics.json()
    assert "overall_tool_failure_rate" in metrics_data
    assert "agent_latency_avg_ms" in metrics_data

    res_latency = await auth_client.get("/api/v1/observability/latency")
    assert res_latency.status_code == 200
    latency_data = res_latency.json()
    assert "agent" in latency_data
    assert "llm" in latency_data
    assert "mcp" in latency_data


@pytest.mark.asyncio
async def test_api_tools_and_alerts_endpoints(auth_client: AsyncClient):
    """Verify GET /api/v1/observability/tools, alerts list, and resolve endpoint."""
    AgentObservabilityService.record_tool_call("api_tool", 30.0, success=True)
    alert = AgentObservabilityService.raise_alert(
        alert_type=AlertType.REPEATED_TOOL_FAILURE,
        severity=AlertSeverity.WARNING,
        title="API Alert Test",
        message="Testing alert endpoint",
        source="tool:api_tool",
    )

    # 1. Tools endpoint
    res_tools = await auth_client.get("/api/v1/observability/tools")
    assert res_tools.status_code == 200
    tools_data = res_tools.json()
    assert any(t["tool_name"] == "api_tool" for t in tools_data)

    # 2. Alerts endpoint
    res_alerts = await auth_client.get("/api/v1/observability/alerts")
    assert res_alerts.status_code == 200
    alerts_data = res_alerts.json()
    assert any(a["id"] == alert.id for a in alerts_data)

    # 3. Resolve alert endpoint
    res_resolve = await auth_client.post(f"/api/v1/observability/alerts/{alert.id}/resolve")
    assert res_resolve.status_code == 200
    assert res_resolve.json()["resolved"] is True
    assert alert.resolved is True


@pytest.mark.asyncio
async def test_api_diagnostics_endpoint(auth_client: AsyncClient, test_user: User):
    """Verify GET /api/v1/observability/diagnostics/{run_id}."""
    run = AgentTraceService.start_run(
        user_id=test_user.id,
        trigger="API_DIAGNOSTIC",
        summary="Testing diagnostics endpoint",
    )
    AgentTraceService.record_event(
        run_id=run.id,
        user_id=test_user.id,
        event_type=ExecutionEventType.TOOL_RESULT,
        status=EventStatus.FAILED,
        short_explanation="Permission denied executing administrative tool.",
        tool_name="admin_tool",
    )
    AgentTraceService.finish_run(run.id, test_user.id, status=EventStatus.FAILED)

    res = await auth_client.get(f"/api/v1/observability/diagnostics/{run.id}")
    assert res.status_code == 200
    diag = res.json()
    assert diag["run_id"] == run.id
    assert diag["is_failure"] is True
    assert diag["failure_category"] == "PERMISSION_DENIED"
    assert "Permission denied" in diag["failure_root_cause"]
    assert len(diag["operator_recommendations"]) >= 1
