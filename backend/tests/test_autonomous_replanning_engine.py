import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.plan import Plan, PlanStatus
from app.db.models.task import GoalDecomposition, Task, TaskDependency, TaskStatus
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.main import app
from app.schemas.plan import PlanCreateRequest
from app.services.planning import PlanningService
from app.services.replanning import (
    AutonomousReplanningEngine,
    PlanDiff,
    ReplanningDecision,
    ReplanningEvent,
    ReplanningReason,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory() -> async_sessionmaker:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def db_session(session_factory: async_sessionmaker) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"replan_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="mockpassword",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def setup_goal_with_plan(
    db: AsyncSession,
    user: User,
    deadline_days: int = 30,
) -> tuple[Goal, Plan, list[Task]]:
    """Helper to set up a Goal, Decomposition, Tasks, Dependencies, and an initial Plan v1."""
    now = datetime.now(UTC)
    goal = Goal(
        user_id=user.id,
        title="Autonomous Platform Deployment",
        objective="Deploy scalable agent engine",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.HIGH,
        deadline=now + timedelta(days=deadline_days),
    )
    db.add(goal)
    await db.flush()

    decomp = GoalDecomposition(goal_id=goal.id, version=1, is_active=True)
    db.add(decomp)
    await db.flush()

    # 3 Tasks in sequence: t1 -> t2 -> t3
    t1 = Task(
        goal_id=goal.id,
        title="Database Setup",
        status=TaskStatus.IN_PROGRESS,
        priority=GoalPriority.HIGH,
        estimated_minutes=120,
        version=1,
    )
    t2 = Task(
        goal_id=goal.id,
        title="Core Logic",
        status=TaskStatus.PENDING,
        priority=GoalPriority.CRITICAL,
        estimated_minutes=240,
        version=1,
    )
    t3 = Task(
        goal_id=goal.id,
        title="Integration Tests",
        status=TaskStatus.PENDING,
        priority=GoalPriority.HIGH,
        estimated_minutes=180,
        version=1,
    )
    db.add_all([t1, t2, t3])
    await db.flush()

    dep1 = TaskDependency(
        task_id=t2.id, depends_on_task_id=t1.id, dependency_type="FINISH_TO_START"
    )
    dep2 = TaskDependency(
        task_id=t3.id, depends_on_task_id=t2.id, dependency_type="FINISH_TO_START"
    )
    db.add_all([dep1, dep2])
    await db.commit()

    # Generate initial Plan v1
    plan_v1_resp = await PlanningService.generate_plan(
        db=db,
        goal_id=goal.id,
        user_id=user.id,
        request=PlanCreateRequest(
            daily_available_hours=5.0,
            workdays_only=True,
            daily_start_hour=9,
            reason="Initial base schedule v1",
        ),
    )
    plan_v1_q = select(Plan).where(Plan.id == plan_v1_resp.id)
    plan_v1_res = await db.execute(plan_v1_q)
    plan_v1 = plan_v1_res.scalar_one()

    return goal, plan_v1, [t1, t2, t3]


@pytest.mark.asyncio
async def test_replan_deadline_moved_earlier(db_session: AsyncSession, test_user: User):
    """Test 1: Deadline moved earlier causes plan invalidation, generates new versioned plan with explainable diff."""
    goal, plan_v1, tasks = await setup_goal_with_plan(db_session, test_user, deadline_days=30)
    assert plan_v1.version == 1
    assert plan_v1.status == PlanStatus.ACTIVE

    # Move deadline to tomorrow (imminent pressure)
    now = datetime.now(UTC)
    new_deadline = now + timedelta(days=2)

    event = ReplanningEvent(
        goal_id=goal.id,
        user_id=test_user.id,
        reason=ReplanningReason.DEADLINE_CHANGED,
        description="Client moved milestone launch date earlier by 28 days.",
        details={"new_deadline": new_deadline.isoformat()},
    )

    decision = await AutonomousReplanningEngine.process_event(
        db=db_session,
        event=event,
        commit=True,
    )

    assert isinstance(decision, ReplanningDecision)
    assert decision.replanning_required is True
    assert decision.previous_plan_version == 1
    assert decision.new_plan_version == 2
    assert decision.action_taken in ("PLAN_COMMITTED", "PLAN_COMMITTED_INFEASIBLE")

    # Verify previous plan was NOT deleted or overwritten, but marked SUPERSEDED
    await db_session.refresh(plan_v1)
    assert plan_v1.status == PlanStatus.SUPERSEDED
    assert plan_v1.version == 1

    # Verify diff explainability
    diff = decision.diff
    assert isinstance(diff, PlanDiff)
    assert diff.old_plan_version == 1
    assert diff.new_plan_version == 2
    assert "DEADLINE_CHANGED" in diff.why_changed
    assert len(diff.why_feasible) > 0


@pytest.mark.asyncio
async def test_replan_deadline_moved_later(db_session: AsyncSession, test_user: User):
    """Test 2: Deadline moved later relaxes pressure and updates risk assessment."""
    goal, plan_v1, tasks = await setup_goal_with_plan(db_session, test_user, deadline_days=3)

    now = datetime.now(UTC)
    new_deadline = now + timedelta(days=60)

    event = ReplanningEvent(
        goal_id=goal.id,
        user_id=test_user.id,
        reason=ReplanningReason.DEADLINE_CHANGED,
        description="Deadline extended by 2 months.",
        details={"new_deadline": new_deadline.isoformat()},
    )

    decision = await AutonomousReplanningEngine.process_event(
        db=db_session,
        event=event,
        commit=True,
    )

    assert decision.replanning_required is True
    assert decision.new_plan_version == 2
    assert decision.is_feasible is True
    assert decision.diff.new_risk_level == "LOW"


@pytest.mark.asyncio
async def test_replan_available_time_reduced(db_session: AsyncSession, test_user: User):
    """Test 3: Available time reduced from 5.0h to 2.0h/day reschedules tasks across more days."""
    goal, plan_v1, tasks = await setup_goal_with_plan(db_session, test_user, deadline_days=45)

    event = ReplanningEvent(
        goal_id=goal.id,
        user_id=test_user.id,
        reason=ReplanningReason.AVAILABLE_TIME_CHANGED,
        description="User daily bandwidth reduced due to on-call duties.",
        details={"daily_available_hours": 2.0},
    )

    decision = await AutonomousReplanningEngine.process_event(
        db=db_session,
        event=event,
        commit=True,
    )

    assert decision.replanning_required is True
    assert decision.new_plan_version == 2
    assert len(decision.diff.tasks_rescheduled) > 0

    # Tasks scheduled under 2h daily capacity end later than under 5h daily capacity
    assert decision.diff.new_completion_date > decision.diff.old_completion_date


@pytest.mark.asyncio
async def test_replan_task_failure(db_session: AsyncSession, test_user: User):
    """Test 4: Task failure triggers replanning, flags error, and adapts schedule."""
    goal, plan_v1, tasks = await setup_goal_with_plan(db_session, test_user, deadline_days=30)
    failed_task = tasks[0]

    event = ReplanningEvent(
        goal_id=goal.id,
        user_id=test_user.id,
        reason=ReplanningReason.TASK_FAILED,
        description=f"Task '{failed_task.title}' failed during automated execution.",
        details={"task_id": str(failed_task.id), "error": "Database timeout error"},
    )

    decision = await AutonomousReplanningEngine.process_event(
        db=db_session,
        event=event,
        commit=True,
    )

    assert decision.replanning_required is True
    assert decision.new_plan_version == 2
    assert "TASK_FAILED" in decision.diff.why_changed

    # Check task status updated to BLOCKED
    await db_session.refresh(failed_task)
    assert failed_task.status == TaskStatus.BLOCKED


@pytest.mark.asyncio
async def test_replan_blocked_dependency(db_session: AsyncSession, test_user: User):
    """Test 5: Blocked dependency shifts downstream tasks and updates diff."""
    goal, plan_v1, tasks = await setup_goal_with_plan(db_session, test_user, deadline_days=30)
    blocked_task = tasks[0]

    event = ReplanningEvent(
        goal_id=goal.id,
        user_id=test_user.id,
        reason=ReplanningReason.TASK_BLOCKED,
        description=f"Task '{blocked_task.title}' is blocked pending third-party API keys.",
        details={"task_id": str(blocked_task.id)},
    )

    decision = await AutonomousReplanningEngine.process_event(
        db=db_session,
        event=event,
        commit=True,
    )

    assert decision.replanning_required is True
    assert decision.new_plan_version == 2
    assert "TASK_BLOCKED" in decision.diff.why_changed


@pytest.mark.asyncio
async def test_replan_new_high_priority_requirement(db_session: AsyncSession, test_user: User):
    """Test 6: New high-priority requirement task added to plan, verified in tasks_added diff."""
    goal, plan_v1, tasks = await setup_goal_with_plan(db_session, test_user, deadline_days=30)

    event = ReplanningEvent(
        goal_id=goal.id,
        user_id=test_user.id,
        reason=ReplanningReason.NEW_REQUIREMENT,
        description="New compliance security audit required before launch.",
        details={
            "title": "Security Compliance Audit",
            "priority": "CRITICAL",
            "estimated_minutes": 180,
        },
    )

    decision = await AutonomousReplanningEngine.process_event(
        db=db_session,
        event=event,
        commit=True,
    )

    assert decision.replanning_required is True
    assert decision.new_plan_version == 2
    assert len(decision.diff.tasks_added) == 1
    assert decision.diff.tasks_added[0]["title"] == "Security Compliance Audit"
    assert "Security Compliance Audit" in decision.explanation


@pytest.mark.asyncio
async def test_never_silently_replace_previous_plan(db_session: AsyncSession, test_user: User):
    """Requirement: Never silently replace the previous plan; preserve historical plan versions."""
    goal, plan_v1, tasks = await setup_goal_with_plan(db_session, test_user, deadline_days=30)

    event = ReplanningEvent(
        goal_id=goal.id,
        user_id=test_user.id,
        reason=ReplanningReason.AVAILABLE_TIME_CHANGED,
        description="Schedule capacity adjustment.",
        details={"daily_available_hours": 4.0},
    )

    decision = await AutonomousReplanningEngine.process_event(
        db=db_session,
        event=event,
        commit=True,
    )

    assert decision.new_plan_version == 2
    assert decision.action_taken == "PLAN_COMMITTED"

    # Query all plans for this goal
    plans_q = select(Plan).where(Plan.goal_id == goal.id).order_by(Plan.version.asc())
    plans_res = await db_session.execute(plans_q)
    all_plans = plans_res.scalars().all()

    # Must contain both Version 1 and Version 2
    assert len(all_plans) == 2
    assert all_plans[0].version == 1
    assert all_plans[0].status == PlanStatus.SUPERSEDED
    assert all_plans[1].version == 2
    assert all_plans[1].status == PlanStatus.ACTIVE


@pytest.mark.asyncio
async def test_replan_preview_does_not_commit(db_session: AsyncSession, test_user: User):
    """Requirement: replan preview calculates candidate changes without committing to DB."""
    goal, plan_v1, tasks = await setup_goal_with_plan(db_session, test_user, deadline_days=30)

    event = ReplanningEvent(
        goal_id=goal.id,
        user_id=test_user.id,
        reason=ReplanningReason.DEADLINE_CHANGED,
        description="Previewing deadline move.",
        details={"new_deadline": (datetime.now(UTC) + timedelta(days=10)).isoformat()},
    )

    # Preview with commit=False
    decision = await AutonomousReplanningEngine.process_event(
        db=db_session,
        event=event,
        commit=False,
    )

    assert decision.action_taken == "PLAN_PREVIEWED"
    assert decision.diff is not None

    # Verify no new plan was committed to DB
    plans_q = select(Plan).where(Plan.goal_id == goal.id)
    plans_res = await db_session.execute(plans_q)
    all_plans = plans_res.scalars().all()

    assert len(all_plans) == 1
    assert all_plans[0].version == 1
    assert all_plans[0].status == PlanStatus.ACTIVE


@pytest.mark.asyncio
async def test_api_replan_endpoints(db_session: AsyncSession, test_user: User):
    """Test the POST /api/v1/goals/{goal_id}/replan and /preview API endpoints."""
    goal, plan_v1, tasks = await setup_goal_with_plan(db_session, test_user, deadline_days=30)

    token, _, _ = create_access_token(subject=str(test_user.id))

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: test_user

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # 1. Test Preview endpoint
            resp_prev = await client.post(
                f"/api/v1/goals/{goal.id}/replan/preview",
                json={
                    "reason": "DEADLINE_CHANGED",
                    "description": "API preview test",
                    "details": {
                        "new_deadline": (datetime.now(UTC) + timedelta(days=15)).isoformat()
                    },
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp_prev.status_code == 200
            prev_data = resp_prev.json()
            assert prev_data["action_taken"] == "PLAN_PREVIEWED"
            assert prev_data["diff"] is not None

            # 2. Test Commit endpoint
            resp_commit = await client.post(
                f"/api/v1/goals/{goal.id}/replan",
                json={
                    "reason": "AVAILABLE_TIME_CHANGED",
                    "description": "API commit test",
                    "details": {"daily_available_hours": 3.5},
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp_commit.status_code == 200
            commit_data = resp_commit.json()
            assert commit_data["action_taken"] == "PLAN_COMMITTED"
            assert commit_data["new_plan_version"] == 2
            assert commit_data["diff"]["why_changed"] != ""
    finally:
        app.dependency_overrides.clear()
