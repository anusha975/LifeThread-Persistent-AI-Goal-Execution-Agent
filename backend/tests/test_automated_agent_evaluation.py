import uuid

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.middleware.security import get_rate_limiter
from app.services.agent_evaluation.models import (
    AgentEvaluationReport,
    EvaluationPillar,
)
from app.services.agent_evaluation.suite import AgentEvaluationSuite
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
        email=f"evaluation_suite_{uuid.uuid4().hex[:8]}@example.com",
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
# 1. Individual Pillar Scenario Tests (All 10 Pillars)
# =============================================================================


@pytest.mark.asyncio
async def test_pillar_1_goal_understanding(db_session: AsyncSession, test_user: User):
    """Pillar 1: Scenario evaluation for goal understanding."""
    result = await AgentEvaluationSuite.evaluate_goal_understanding(db_session, test_user.id)
    assert result.pillar == EvaluationPillar.GOAL_UNDERSTANDING
    assert result.input is not None
    assert result.expected_behavior is not None
    assert result.actual_behavior is not None
    assert result.passed is True
    assert result.score >= 0.8
    assert "checks" in result.evaluation_metadata


@pytest.mark.asyncio
async def test_pillar_2_goal_decomposition(db_session: AsyncSession, test_user: User):
    """Pillar 2: Scenario evaluation for goal decomposition."""
    result = await AgentEvaluationSuite.evaluate_goal_decomposition(db_session, test_user.id)
    assert result.pillar == EvaluationPillar.GOAL_DECOMPOSITION
    assert result.input is not None
    assert result.expected_behavior is not None
    assert result.actual_behavior is not None
    assert result.passed is True
    assert result.score >= 0.8
    assert result.evaluation_metadata["milestones_count"] >= 1
    assert result.evaluation_metadata["tasks_count"] >= 2


@pytest.mark.asyncio
async def test_pillar_3_planning(db_session: AsyncSession, test_user: User):
    """Pillar 3: Scenario evaluation for planning."""
    result = await AgentEvaluationSuite.evaluate_planning(db_session, test_user.id)
    assert result.pillar == EvaluationPillar.PLANNING
    assert result.input is not None
    assert result.expected_behavior is not None
    assert result.actual_behavior is not None
    assert result.passed is True
    assert result.score >= 0.8
    assert result.evaluation_metadata["version"] == 1


@pytest.mark.asyncio
async def test_pillar_4_memory_retrieval(db_session: AsyncSession, test_user: User):
    """Pillar 4: Scenario evaluation for memory retrieval."""
    result = await AgentEvaluationSuite.evaluate_memory_retrieval(db_session, test_user.id)
    assert result.pillar == EvaluationPillar.MEMORY_RETRIEVAL
    assert result.input is not None
    assert result.expected_behavior is not None
    assert result.actual_behavior is not None
    assert result.passed is True
    assert result.score >= 0.8
    assert result.evaluation_metadata["recalled_count"] >= 1


@pytest.mark.asyncio
async def test_pillar_5_tool_selection(db_session: AsyncSession, test_user: User):
    """Pillar 5: Scenario evaluation for tool selection."""
    result = await AgentEvaluationSuite.evaluate_tool_selection(db_session, test_user.id)
    assert result.pillar == EvaluationPillar.TOOL_SELECTION
    assert result.input is not None
    assert result.expected_behavior is not None
    assert result.actual_behavior is not None
    assert result.passed is True
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_pillar_6_constraint_handling(db_session: AsyncSession, test_user: User):
    """Pillar 6: Scenario evaluation for constraint handling."""
    result = await AgentEvaluationSuite.evaluate_constraint_handling(db_session, test_user.id)
    assert result.pillar == EvaluationPillar.CONSTRAINT_HANDLING
    assert result.input is not None
    assert result.expected_behavior is not None
    assert result.actual_behavior is not None
    assert result.passed is True
    assert result.score >= 0.8


@pytest.mark.asyncio
async def test_pillar_7_replanning(db_session: AsyncSession, test_user: User):
    """Pillar 7: Scenario evaluation for replanning."""
    result = await AgentEvaluationSuite.evaluate_replanning(db_session, test_user.id)
    assert result.pillar == EvaluationPillar.REPLANNING
    assert result.input is not None
    assert result.expected_behavior is not None
    assert result.actual_behavior is not None
    assert result.passed is True
    assert result.score >= 0.8
    assert result.evaluation_metadata["new_version"] >= 2


@pytest.mark.asyncio
async def test_pillar_8_failure_recovery(db_session: AsyncSession, test_user: User):
    """Pillar 8: Scenario evaluation for failure recovery."""
    result = await AgentEvaluationSuite.evaluate_failure_recovery(db_session, test_user.id)
    assert result.pillar == EvaluationPillar.FAILURE_RECOVERY
    assert result.input is not None
    assert result.expected_behavior is not None
    assert result.actual_behavior is not None
    assert result.passed is True
    assert result.score == 1.0
    assert result.evaluation_metadata["attempts"] == 2
    assert result.evaluation_metadata["final_action"] == "RECOVERED_VIA_RETRY"


@pytest.mark.asyncio
async def test_pillar_9_permission_enforcement(db_session: AsyncSession, test_user: User):
    """Pillar 9: Scenario evaluation for permission enforcement."""
    result = await AgentEvaluationSuite.evaluate_permission_enforcement(db_session, test_user.id)
    assert result.pillar == EvaluationPillar.PERMISSION_ENFORCEMENT
    assert result.input is not None
    assert result.expected_behavior is not None
    assert result.actual_behavior is not None
    assert result.passed is True
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_pillar_10_prompt_injection_resistance(db_session: AsyncSession, test_user: User):
    """Pillar 10: Scenario evaluation for prompt injection resistance."""
    result = await AgentEvaluationSuite.evaluate_prompt_injection_resistance(db_session, test_user.id)
    assert result.pillar == EvaluationPillar.PROMPT_INJECTION_RESISTANCE
    assert result.input is not None
    assert result.expected_behavior is not None
    assert result.actual_behavior is not None
    assert result.passed is True
    assert result.score == 1.0
    assert result.evaluation_metadata["detected_count"] == 4


# =============================================================================
# 2. Acceptance Criteria: Automated Suite Execution & Clear Report
# =============================================================================


@pytest.mark.asyncio
async def test_automated_evaluation_suite_run_and_report(
    db_session: AsyncSession,
    test_user: User,
):
    """Acceptance Criteria: The evaluation suite can be executed automatically and produces a clear report."""
    report: AgentEvaluationReport = await AgentEvaluationSuite.run_all_scenarios(
        db=db_session,
        user_id=test_user.id,
    )

    assert report.total_scenarios == 10
    assert report.passed_count == 10
    assert report.failed_count == 0
    assert report.pass_rate == 100.0
    assert len(report.scenarios) == 10
    assert len(report.pillar_scores) == 10
    assert report.duration_ms > 0

    # Verify each pillar is present in the results
    expected_pillars = {p.value for p in EvaluationPillar}
    reported_pillars = {s.pillar.value for s in report.scenarios}
    assert expected_pillars == reported_pillars

    # Verify clear markdown summary report
    assert "# LifeThread Agent Automated Evaluation Report" in report.summary_markdown
    assert "**Pass Rate**: `100.0%`" in report.summary_markdown
    assert "| Scenario ID | Pillar | Outcome |" in report.summary_markdown
    assert "### Pillar Score Breakdown" in report.summary_markdown


# =============================================================================
# 3. REST API Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
async def test_api_run_evaluation_endpoint(auth_client: AsyncClient):
    """Verify POST /api/v1/evaluation/run executes the suite and returns the report."""
    res = await auth_client.post("/api/v1/evaluation/run")
    assert res.status_code == 200
    report_data = res.json()

    assert report_data["total_scenarios"] == 10
    assert report_data["passed_count"] == 10
    assert report_data["pass_rate"] == 100.0
    assert len(report_data["scenarios"]) == 10
    assert "summary_markdown" in report_data


@pytest.mark.asyncio
async def test_api_latest_and_pillars_endpoints(auth_client: AsyncClient):
    """Verify GET /api/v1/evaluation/latest and GET /api/v1/evaluation/pillars."""
    # 1. Pillars list
    res_pillars = await auth_client.get("/api/v1/evaluation/pillars")
    assert res_pillars.status_code == 200
    pillars_data = res_pillars.json()
    assert pillars_data["total_pillars"] == 10
    assert len(pillars_data["pillars"]) == 10

    # 2. Latest report
    res_latest = await auth_client.get("/api/v1/evaluation/latest")
    assert res_latest.status_code == 200
    latest_data = res_latest.json()
    assert latest_data["total_scenarios"] == 10
    assert latest_data["pass_rate"] == 100.0
