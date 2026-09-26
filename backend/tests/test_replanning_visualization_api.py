import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.task import GoalDecomposition, Task, TaskStatus
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.services.planning import PlanningService
from app.services.replanning import (
    AutonomousReplanningEngine,
    ReplanningEvent,
    ReplanningReason,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(async_db: AsyncSession):
    async def override_get_db():
        yield async_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_replanning_visualization_api_full_flow(async_db: AsyncSession, client: AsyncClient):
    """Test Module 31: Replanning Visualization API.

    Validates:
    - PLAN CHANGED banner
    - Actual Reason
    - Previous Plan real data
    - New Plan real data
    - Changes: added tasks, removed tasks, rescheduled tasks, changed priorities
    - WHY? explanation based on actual replanning metadata without private CoT
    - Strict tenant isolation
    """
    now = datetime.now(UTC)

    # 1. Create User
    user = User(
        id=uuid.uuid4(),
        email="replan_visual_user@example.com",
        password_hash="pw",
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        email="replan_other_user@example.com",
        password_hash="pw",
        is_active=True,
    )
    async_db.add_all([user, user_b])
    await async_db.commit()

    # 2. Create Goal
    goal = Goal(
        id=uuid.uuid4(),
        user_id=user.id,
        title="Launch Autonomous Microservice",
        objective="Deploy containerized microservice to Kubernetes cluster",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.CRITICAL,
        deadline=now + timedelta(days=7),
    )
    async_db.add(goal)
    await async_db.commit()

    # 3. Create Decomposition and Tasks
    decomp = GoalDecomposition(
        id=uuid.uuid4(),
        goal_id=goal.id,
        version=1,
        is_active=True,
    )
    async_db.add(decomp)

    task1 = Task(
        goal_id=goal.id,
        title="Write Dockerfile and healthcheck",
        priority=GoalPriority.MEDIUM,
        status=TaskStatus.COMPLETED,
        estimated_minutes=120,
        version=1,
    )
    task2 = Task(
        goal_id=goal.id,
        title="Configure Kubernetes deployment manifests",
        priority=GoalPriority.HIGH,
        status=TaskStatus.PENDING,
        estimated_minutes=180,
        version=1,
    )
    task3 = Task(
        goal_id=goal.id,
        title="Execute canary rollout validation",
        priority=GoalPriority.CRITICAL,
        status=TaskStatus.PENDING,
        estimated_minutes=240,
        version=1,
    )
    async_db.add_all([task1, task2, task3])
    await async_db.commit()

    # 4. Generate Initial Baseline Plan (v1)
    from app.schemas.plan import PlanCreateRequest
    plan_v1_resp = await PlanningService.generate_plan(
        db=async_db,
        goal_id=goal.id,
        user_id=user.id,
        request=PlanCreateRequest(
            daily_available_hours=4.0,
            start_date=now,
            reason="Initial baseline schedule",
        ),
    )
    assert plan_v1_resp.version == 1

    token_a, _, _ = create_access_token(subject=str(user.id))
    headers_a = {"Authorization": f"Bearer {token_a}"}

    token_b, _, _ = create_access_token(subject=str(user_b.id))
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Verify endpoint when only initial plan exists
    res_init = await client.get(f"/api/v1/goals/{goal.id}/replanning-diff", headers=headers_a)
    assert res_init.status_code == 200
    init_data = res_init.json()
    assert init_data["plan_changed"] is False
    assert init_data["status_label"] == "INITIAL PLAN"

    # 5. Trigger a Real Replanning Event (Deadline shortened by 3 days & available time changed)
    replan_event = ReplanningEvent(
        goal_id=goal.id,
        user_id=user.id,
        reason=ReplanningReason.DEADLINE_CHANGED,
        description="Executive brought deployment deadline forward by 72 hours",
        details={
            "old_deadline": (now + timedelta(days=7)).isoformat(),
            "new_deadline": (now + timedelta(days=4)).isoformat(),
            "daily_available_hours": 6.0,
        },
    )
    decision = await AutonomousReplanningEngine.process_event(
        db=async_db,
        event=replan_event,
        commit=True,
    )
    assert "PLAN_COMMITTED" in decision.action_taken
    assert decision.new_plan_version == 2
    assert decision.diff is not None

    # 6. Fetch Replanning Diff via REST API
    res_diff = await client.get(f"/api/v1/goals/{goal.id}/replanning-diff", headers=headers_a)
    assert res_diff.status_code == 200
    diff_data = res_diff.json()

    # ACCEPTANCE CRITERIA CHECKS:
    # 1. PLAN CHANGED banner
    assert diff_data["plan_changed"] is True
    assert diff_data["status_label"] == "PLAN CHANGED"

    # 2. Reason: actual reason
    assert diff_data["reason"] == "DEADLINE_CHANGED"

    # 3. Previous plan real data
    assert diff_data["previous_plan"] is not None
    assert diff_data["previous_plan"]["version"] == 1
    assert diff_data["previous_plan"]["task_count"] > 0
    assert diff_data["previous_plan"]["total_duration_minutes"] > 0
    assert diff_data["previous_plan"]["scheduled_end"] is not None

    # 4. New plan real data
    assert diff_data["new_plan"] is not None
    assert diff_data["new_plan"]["version"] == 2
    assert diff_data["new_plan"]["task_count"] > 0
    assert diff_data["new_plan"]["total_duration_minutes"] > 0

    # 5. Changes breakdown:
    changes = diff_data["changes"]
    assert changes is not None
    assert "tasks_added" in changes
    assert "tasks_removed" in changes
    assert "tasks_rescheduled" in changes
    assert "priority_changes" in changes

    # 6. WHY? explanation based on actual replanning metadata
    assert diff_data["why_explanation"] is not None
    assert len(diff_data["why_explanation"]) > 0
    assert "DEADLINE_CHANGED" in diff_data["why_explanation"]
    assert "brought deployment deadline forward" in diff_data["why_explanation"]

    # 7. No private chain-of-thought exposed
    assert "chain_of_thought" not in str(diff_data).lower()
    assert "<thought>" not in str(diff_data)
    assert "</thought>" not in str(diff_data)

    # 8. Feasibility rationale
    assert diff_data["why_feasible"] is not None
    assert len(diff_data["why_feasible"]) > 0

    # 9. Strict Multi-Tenant Isolation
    res_idor = await client.get(f"/api/v1/goals/{goal.id}/replanning-diff", headers=headers_b)
    assert res_idor.status_code == 404
