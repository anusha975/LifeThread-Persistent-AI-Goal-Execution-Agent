import uuid

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.services.agent_trace.models import (
    EventStatus,
    ExecutionEventType,
)
from app.services.agent_trace.service import AgentTraceService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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
        email=f"trace_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashedpass",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"other_{uuid.uuid4().hex[:8]}@example.com",
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


@pytest.mark.asyncio
async def test_agent_trace_cycle_progression():
    """Requirement: Trace captures 6-phase sequence:
    Agent Run -> Decision -> Tool Call -> Tool Result -> Evaluation -> State Update.
    """
    user_id = uuid.uuid4()
    goal_id = uuid.uuid4()

    run = AgentTraceService.start_run(
        user_id=user_id,
        trigger="AUTONOMOUS_CYCLE",
        goal_id=goal_id,
        goal_title="Deploy Resilient Microservices",
    )
    assert run.id is not None
    assert run.status == EventStatus.RUNNING
    assert len(run.events) == 1
    assert run.events[0].event_type == ExecutionEventType.AGENT_RUN

    # 1. Decision
    AgentTraceService.record_event(
        run_id=run.id,
        user_id=user_id,
        event_type=ExecutionEventType.DECISION,
        status=EventStatus.SUCCESS,
        short_explanation="Decided to schedule container security scans before production deployment",
        goal_id=goal_id,
    )

    # 2. Tool Call
    AgentTraceService.record_event(
        run_id=run.id,
        user_id=user_id,
        event_type=ExecutionEventType.TOOL_CALL,
        status=EventStatus.SUCCESS,
        short_explanation="Invoked security vulnerability scanner on container image",
        tool_name="scan_container_image",
        tool_parameters={"target": "registry.lifethread.io/app:v1"},
    )

    # 3. Tool Result
    AgentTraceService.record_event(
        run_id=run.id,
        user_id=user_id,
        event_type=ExecutionEventType.TOOL_RESULT,
        status=EventStatus.SUCCESS,
        short_explanation="Scan completed: 0 critical vulnerabilities found",
        tool_name="scan_container_image",
        tool_result={"vulnerabilities": 0, "status": "PASSED"},
    )

    # 4. Evaluation
    AgentTraceService.record_event(
        run_id=run.id,
        user_id=user_id,
        event_type=ExecutionEventType.EVALUATION,
        status=EventStatus.SUCCESS,
        short_explanation="Evaluated security policy threshold: Meets acceptance criteria for release",
    )

    # 5. State Update
    AgentTraceService.record_event(
        run_id=run.id,
        user_id=user_id,
        event_type=ExecutionEventType.STATE_UPDATE,
        status=EventStatus.SUCCESS,
        short_explanation="Updated deployment task status from IN_PROGRESS to READY_FOR_DEPLOYMENT",
        state_changes={"task_status": "READY_FOR_DEPLOYMENT"},
    )

    finished = AgentTraceService.finish_run(run_id=run.id, user_id=user_id, status=EventStatus.SUCCESS)
    assert finished is not None
    assert finished.status == EventStatus.SUCCESS
    assert finished.completed_at is not None

    # Verify event types strictly follow the 6-phase autonomous sequence
    event_types = [e.event_type for e in finished.events]
    assert event_types == [
        ExecutionEventType.AGENT_RUN,
        ExecutionEventType.DECISION,
        ExecutionEventType.TOOL_CALL,
        ExecutionEventType.TOOL_RESULT,
        ExecutionEventType.EVALUATION,
        ExecutionEventType.STATE_UPDATE,
    ]


@pytest.mark.asyncio
async def test_list_and_get_agent_runs_api(auth_client: AsyncClient, test_user: User, db_session: AsyncSession):
    """Test REST API endpoints for Agent Activity Center."""
    # Create a real goal for the user in the database
    goal = Goal(
        id=uuid.uuid4(),
        user_id=test_user.id,
        title="Master Distributed Systems",
        objective="Learn consensus protocols, raft, paxos, and vector clocks",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.HIGH,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)

    # Query agent runs via API
    resp = await auth_client.get("/api/v1/agent/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert isinstance(runs, list)
    assert len(runs) >= 1

    first_run_id = runs[0]["id"]
    # Get single run detail
    detail_resp = await auth_client.get(f"/api/v1/agent/runs/{first_run_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == first_run_id
    assert "events" in detail
    assert len(detail["events"]) >= 1

    # Check for presence of required 6-phase events
    event_types = [e["event_type"] for e in detail["events"]]
    assert ExecutionEventType.AGENT_RUN.value in event_types
    assert ExecutionEventType.DECISION.value in event_types
    assert ExecutionEventType.TOOL_CALL.value in event_types
    assert ExecutionEventType.TOOL_RESULT.value in event_types
    assert ExecutionEventType.EVALUATION.value in event_types
    assert ExecutionEventType.STATE_UPDATE.value in event_types

    # Ensure no hidden chain-of-thought or private model reasoning
    for event in detail["events"]:
        assert "short_explanation" in event
        assert "chain_of_thought" not in event
        assert "internal_thoughts" not in event
        assert "private_reasoning" not in event


@pytest.mark.asyncio
async def test_agent_run_tenant_isolation(
    auth_client: AsyncClient,
    test_user: User,
    other_user: User,
):
    """Ensure users cannot access another user's agent execution runs."""
    other_run = AgentTraceService.start_run(
        user_id=other_user.id,
        trigger="PRIVATE_MISSION",
        goal_title="Other User Confidential Project",
    )
    AgentTraceService.finish_run(run_id=other_run.id, user_id=other_user.id)

    # Attempt to retrieve other_user's run as test_user
    resp = await auth_client.get(f"/api/v1/agent/runs/{other_run.id}")
    assert resp.status_code == 404
