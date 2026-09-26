import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.task import GoalDecomposition, Task, TaskDependency, TaskStatus
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.main import app
from app.services.goal_evaluation import (
    GoalEvaluation,
    GoalEvaluationEngine,
    Weakness,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def test_user_id() -> uuid.UUID:
    return uuid.uuid4()


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
        email=f"eval_test_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="mockpasswordhash",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def create_mock_goal(user_id: uuid.UUID, deadline: datetime | None = None) -> Goal:
    return Goal(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Launch Autonomous Agent Core",
        objective="Deploy scalable agent backend with automated planning and evaluation",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.HIGH,
        deadline=deadline,
    )


def test_weighted_progress_vs_simple_completion(test_user_id: uuid.UUID):
    """Requirement: Use weighted progress rather than simply completed_tasks / total_tasks.

    Demonstrates that completing high-priority, high-workload tasks yields much higher
    weighted progress than completing low-priority trivial tasks.
    """
    goal = create_mock_goal(test_user_id)

    # Scenario A: 1 out of 4 tasks is completed, BUT it is a CRITICAL, 4-hour task on the Critical Path
    task_cp_critical = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Core Engine Architecture",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.CRITICAL,
        estimated_minutes=240,
        version=1,
    )
    task_minor_1 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Minor Readme Formatting",
        status=TaskStatus.PENDING,
        priority=GoalPriority.LOW,
        estimated_minutes=15,
        version=1,
    )
    task_minor_2 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Favicon Update",
        status=TaskStatus.PENDING,
        priority=GoalPriority.LOW,
        estimated_minutes=15,
        version=1,
    )
    task_minor_3 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Add Code Comments",
        status=TaskStatus.PENDING,
        priority=GoalPriority.LOW,
        estimated_minutes=15,
        version=1,
    )

    tasks_scenario_a = [task_cp_critical, task_minor_1, task_minor_2, task_minor_3]
    eval_a = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal,
        tasks=tasks_scenario_a,
        dependencies=[],
        critical_path_ids=[task_cp_critical.id],
    )

    # Raw completion is only 1/4 = 0.25 (25%)
    assert eval_a.completion_ratio == 0.25
    # Weighted progress is significantly higher (> 0.70) because the critical 4-hour task dominates the goal
    assert eval_a.weighted_progress > 0.70

    # Scenario B: 3 out of 4 tasks are completed, but they are all minor 15m LOW priority tasks
    task_cp_critical_pending = Task(
        id=task_cp_critical.id,
        goal_id=goal.id,
        title="Core Engine Architecture",
        status=TaskStatus.PENDING,
        priority=GoalPriority.CRITICAL,
        estimated_minutes=240,
        version=1,
    )
    task_minor_1_done = Task(
        id=task_minor_1.id,
        goal_id=goal.id,
        title="Minor Readme Formatting",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.LOW,
        estimated_minutes=15,
        version=1,
    )
    task_minor_2_done = Task(
        id=task_minor_2.id,
        goal_id=goal.id,
        title="Favicon Update",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.LOW,
        estimated_minutes=15,
        version=1,
    )
    task_minor_3_done = Task(
        id=task_minor_3.id,
        goal_id=goal.id,
        title="Add Code Comments",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.LOW,
        estimated_minutes=15,
        version=1,
    )

    tasks_scenario_b = [
        task_cp_critical_pending,
        task_minor_1_done,
        task_minor_2_done,
        task_minor_3_done,
    ]
    eval_b = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal,
        tasks=tasks_scenario_b,
        dependencies=[],
        critical_path_ids=[task_cp_critical.id],
    )

    # Raw completion is 3/4 = 0.75 (75%)
    assert eval_b.completion_ratio == 0.75
    # But weighted progress is much lower (< 0.20) because the core heavy task hasn't even started
    assert eval_b.weighted_progress < 0.20


def test_is_moving_forward_determination(test_user_id: uuid.UUID):
    """Requirement: Determine whether the user's current plan is actually moving the goal forward."""
    goal = create_mock_goal(test_user_id)

    # Case 1: Healthy momentum: 1 completed, 1 in progress, 1 pending
    t1 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Task 1",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.HIGH,
        estimated_minutes=60,
        version=1,
    )
    t2 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Task 2",
        status=TaskStatus.IN_PROGRESS,
        priority=GoalPriority.HIGH,
        estimated_minutes=60,
        version=1,
    )
    t3 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Task 3",
        status=TaskStatus.PENDING,
        priority=GoalPriority.MEDIUM,
        estimated_minutes=60,
        version=1,
    )

    eval_healthy = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal,
        tasks=[t1, t2, t3],
        dependencies=[],
        critical_path_ids=[t1.id, t2.id, t3.id],
    )
    assert eval_healthy.is_moving_forward is True
    assert "actively moving forward" in eval_healthy.summary

    # Case 2: Deadlock: Critical path task is blocked by unfinished prerequisite
    t_blocker = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Unfinished Prereq",
        status=TaskStatus.BLOCKED,
        priority=GoalPriority.HIGH,
        estimated_minutes=60,
        version=1,
    )
    t_cp = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Main Critical Task",
        status=TaskStatus.PENDING,
        priority=GoalPriority.CRITICAL,
        estimated_minutes=120,
        version=1,
    )

    dep = TaskDependency(
        task_id=t_cp.id,
        depends_on_task_id=t_blocker.id,
        dependency_type="FINISH_TO_START",
    )

    eval_stalled = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal,
        tasks=[t_blocker, t_cp],
        dependencies=[dep],
        critical_path_ids=[t_cp.id],
    )
    assert eval_stalled.is_moving_forward is False
    assert "stalled" in eval_stalled.summary
    assert eval_stalled.risk_assessment.overall_risk == "CRITICAL"


def test_blocked_dependencies_and_weaknesses(test_user_id: uuid.UUID):
    """Requirement: Identify blocked dependencies and extract structured weaknesses."""
    goal = create_mock_goal(test_user_id)

    task_a = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Setup Database",
        status=TaskStatus.IN_PROGRESS,
        priority=GoalPriority.HIGH,
        estimated_minutes=60,
        version=1,
    )
    task_b = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Run Schema Migrations",
        status=TaskStatus.PENDING,
        priority=GoalPriority.HIGH,
        estimated_minutes=30,
        version=1,
    )
    task_c = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Seed Test Users",
        status=TaskStatus.PENDING,
        priority=GoalPriority.MEDIUM,
        estimated_minutes=30,
        version=1,
    )

    # Dependency: B depends on A, C depends on B
    deps = [
        TaskDependency(
            task_id=task_b.id, depends_on_task_id=task_a.id, dependency_type="FINISH_TO_START"
        ),
        TaskDependency(
            task_id=task_c.id, depends_on_task_id=task_b.id, dependency_type="FINISH_TO_START"
        ),
    ]

    eval_result = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal,
        tasks=[task_a, task_b, task_c],
        dependencies=deps,
        critical_path_ids=[task_a.id, task_b.id],
    )

    assert eval_result.blocked_dependencies_count == 2
    assert (
        eval_result.blocked_tasks == 2
    )  # Task B and C are both blocked by unfinished predecessors

    # Weaknesses must include CRITICAL_PATH_BOTTLENECK because Task B is on critical path and blocked
    categories = [w.category for w in eval_result.weaknesses]
    assert "CRITICAL_PATH_BOTTLENECK" in categories
    for w in eval_result.weaknesses:
        assert isinstance(w, Weakness)
        assert w.confidence > 0.8
        assert w.mitigation_strategy != ""


def test_recent_failures_impact(test_user_id: uuid.UUID):
    """Requirement: Detect recent failures and assess their impact on risk and consistency."""
    goal = create_mock_goal(test_user_id)

    task_normal = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Normal Task",
        status=TaskStatus.IN_PROGRESS,
        priority=GoalPriority.MEDIUM,
        estimated_minutes=60,
        version=1,
    )
    task_failed = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Failed API Integration",
        status=TaskStatus.BLOCKED,
        priority=GoalPriority.HIGH,
        estimated_minutes=90,
        version=1,
    )
    task_failed.metadata_json = {
        "failure_count": 3,
        "recent_error": "ConnectionRefusedError: port 5432 unreachable",
    }

    eval_result = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal,
        tasks=[task_normal, task_failed],
        dependencies=[],
        critical_path_ids=[],
    )

    assert eval_result.recent_failures_count >= 1
    assert eval_result.consistency_score < 0.70  # Failure penalty applied
    assert eval_result.risk_assessment.failure_risk in ("MEDIUM", "HIGH", "CRITICAL")

    # Weakness must note execution failure churn
    weakness_categories = [w.category for w in eval_result.weaknesses]
    assert "EXECUTION_FAILURE_CHURN" in weakness_categories


def test_deadline_risk_variations(test_user_id: uuid.UUID):
    """Requirement: Accurate deadline risk evaluation under varied temporal scenarios."""
    now = datetime.now(UTC)

    # 1. Past deadline with unfinished tasks -> CRITICAL
    goal_passed = create_mock_goal(test_user_id, deadline=now - timedelta(days=1))
    t1 = Task(
        id=uuid.uuid4(),
        goal_id=goal_passed.id,
        title="Unfinished Task",
        status=TaskStatus.PENDING,
        priority=GoalPriority.HIGH,
        estimated_minutes=120,
        version=1,
    )

    eval_passed = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal_passed, tasks=[t1], dependencies=[], critical_path_ids=[], as_of=now
    )
    assert eval_passed.deadline_risk == "CRITICAL"
    assert eval_passed.risk_assessment.deadline_risk_score == 1.0

    # 2. Ample deadline (100 hours remaining for a 2-hour task) -> LOW
    goal_ample = create_mock_goal(test_user_id, deadline=now + timedelta(days=10))
    eval_ample = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal_ample, tasks=[t1], dependencies=[], critical_path_ids=[], as_of=now
    )
    assert eval_ample.deadline_risk == "LOW"
    assert eval_ample.risk_assessment.deadline_risk_score < 0.35

    # 3. Tight deadline (only 2 hours remaining for a 4-hour workload) -> CRITICAL
    goal_tight = create_mock_goal(test_user_id, deadline=now + timedelta(hours=2))
    t_heavy = Task(
        id=uuid.uuid4(),
        goal_id=goal_tight.id,
        title="Heavy Work",
        status=TaskStatus.PENDING,
        priority=GoalPriority.CRITICAL,
        estimated_minutes=240,
        version=1,
    )
    eval_tight = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal_tight, tasks=[t_heavy], dependencies=[], critical_path_ids=[], as_of=now
    )
    assert eval_tight.deadline_risk == "CRITICAL"


def test_performance_scoring_and_estimation_accuracy(test_user_id: uuid.UUID):
    """Requirement: Evaluate performance score based on actual vs estimated effort."""
    goal = create_mock_goal(test_user_id)

    # Fast completion: estimated 60m, completed in 45m
    t_fast = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Fast Task",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.MEDIUM,
        estimated_minutes=60,
        version=1,
    )
    t_fast.metadata_json = {"actual_minutes": 45}

    # Slow completion: estimated 60m, completed in 180m (3x slower)
    t_slow = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Slow Task",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.MEDIUM,
        estimated_minutes=60,
        version=1,
    )
    t_slow.metadata_json = {"actual_minutes": 180}

    eval_fast = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal, tasks=[t_fast], dependencies=[], critical_path_ids=[]
    )
    eval_slow = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal, tasks=[t_slow], dependencies=[], critical_path_ids=[]
    )

    assert eval_fast.performance_score > eval_slow.performance_score
    assert eval_fast.performance_score >= 0.90
    assert eval_slow.performance_score < 0.50


def test_confidence_calculation(test_user_id: uuid.UUID):
    """Requirement: Include confidence values based on data completeness."""
    goal = create_mock_goal(test_user_id)

    # Barebones task without estimates
    t_sparse = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Vague Task",
        status=TaskStatus.PENDING,
        priority=GoalPriority.LOW,
        estimated_minutes=0,
        version=1,
    )
    eval_sparse = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal, tasks=[t_sparse], dependencies=[], critical_path_ids=[]
    )

    # Rich tasks with estimates and completion history
    t_rich_1 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Task 1",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.HIGH,
        estimated_minutes=90,
        version=1,
    )
    t_rich_1.metadata_json = {"actual_minutes": 85}
    t_rich_2 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Task 2",
        status=TaskStatus.IN_PROGRESS,
        priority=GoalPriority.HIGH,
        estimated_minutes=120,
        version=1,
    )
    eval_rich = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal, tasks=[t_rich_1, t_rich_2], dependencies=[], critical_path_ids=[]
    )

    assert eval_rich.confidence > eval_sparse.confidence
    assert eval_rich.confidence >= 0.85


def test_deterministic_results(test_user_id: uuid.UUID):
    """Acceptance Criteria: Evaluation results are deterministic for identical test data and explain major factors."""
    goal = create_mock_goal(test_user_id, deadline=datetime(2026, 10, 1, 12, 0, tzinfo=UTC))
    as_of = datetime(2026, 9, 25, 0, 0, tzinfo=UTC)

    t1 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Task 1",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.HIGH,
        estimated_minutes=120,
        version=1,
    )
    t2 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Task 2",
        status=TaskStatus.IN_PROGRESS,
        priority=GoalPriority.CRITICAL,
        estimated_minutes=180,
        version=1,
    )
    t3 = Task(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Task 3",
        status=TaskStatus.BLOCKED,
        priority=GoalPriority.HIGH,
        estimated_minutes=90,
        version=1,
    )

    dep = TaskDependency(task_id=t3.id, depends_on_task_id=t2.id, dependency_type="FINISH_TO_START")

    eval_1 = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal,
        tasks=[t1, t2, t3],
        dependencies=[dep],
        critical_path_ids=[t2.id, t3.id],
        as_of=as_of,
    )
    eval_2 = GoalEvaluationEngine.evaluate_plan_data(
        goal=goal,
        tasks=[t1, t2, t3],
        dependencies=[dep],
        critical_path_ids=[t2.id, t3.id],
        as_of=as_of,
    )

    # Must be 100% deterministic
    assert eval_1.weighted_progress == eval_2.weighted_progress
    assert eval_1.performance_score == eval_2.performance_score
    assert eval_1.consistency_score == eval_2.consistency_score
    assert eval_1.is_moving_forward == eval_2.is_moving_forward
    assert eval_1.risk_assessment.risk_score == eval_2.risk_assessment.risk_score
    assert eval_1.major_factors == eval_2.major_factors
    assert len(eval_1.major_factors) >= 3


@pytest.mark.asyncio
async def test_async_evaluate_goal_from_db(db_session: AsyncSession, test_user: User):
    """Verify evaluate_goal fetches live DB entities (Goal, Decomposition, Tasks, Dependencies)."""
    # 1. Create Goal
    goal = Goal(
        user_id=test_user.id,
        title="Live DB Evaluation Goal",
        objective="Verify DB query and critical path integration in evaluation",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.HIGH,
    )
    db_session.add(goal)
    await db_session.flush()

    # 2. Create Decomposition
    decomp = GoalDecomposition(
        goal_id=goal.id,
        version=1,
        is_active=True,
    )
    db_session.add(decomp)
    await db_session.flush()

    # 3. Create Tasks
    t1 = Task(
        goal_id=goal.id,
        title="Setup Repo",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.HIGH,
        estimated_minutes=30,
        version=1,
    )
    t2 = Task(
        goal_id=goal.id,
        title="Build Pipeline",
        status=TaskStatus.IN_PROGRESS,
        priority=GoalPriority.CRITICAL,
        estimated_minutes=120,
        version=1,
    )
    db_session.add_all([t1, t2])
    await db_session.flush()

    # 4. Dependency
    dep = TaskDependency(task_id=t2.id, depends_on_task_id=t1.id, dependency_type="FINISH_TO_START")
    db_session.add(dep)
    await db_session.commit()

    # 5. Evaluate
    evaluation = await GoalEvaluationEngine.evaluate_goal(
        db=db_session,
        goal_id=goal.id,
        user_id=test_user.id,
    )

    assert isinstance(evaluation, GoalEvaluation)
    assert evaluation.goal_id == goal.id
    assert evaluation.total_tasks == 2
    assert evaluation.completed_tasks == 1
    assert evaluation.in_progress_tasks == 1
    assert evaluation.is_moving_forward is True
    assert evaluation.weighted_progress > 0.0


@pytest.mark.asyncio
async def test_api_evaluate_goal_endpoint(db_session: AsyncSession, test_user: User):
    """Test the POST /api/v1/goals/{goal_id}/evaluate API endpoint."""
    goal = Goal(
        user_id=test_user.id,
        title="API Evaluation Goal",
        objective="Verify POST evaluate endpoint returns structured evaluation",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.HIGH,
    )
    db_session.add(goal)
    await db_session.flush()

    decomp = GoalDecomposition(goal_id=goal.id, version=1, is_active=True)
    db_session.add(decomp)
    await db_session.flush()

    t1 = Task(
        goal_id=goal.id,
        title="API Tested Task",
        status=TaskStatus.COMPLETED,
        priority=GoalPriority.HIGH,
        estimated_minutes=60,
        version=1,
    )
    db_session.add(t1)
    await db_session.commit()

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
            resp = await client.post(
                f"/api/v1/goals/{goal.id}/evaluate",
                headers={"Authorization": f"Bearer {token}"},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["goal_id"] == str(goal.id)
            assert data["is_moving_forward"] is True
            assert "weighted_progress" in data
            assert "performance_score" in data
            assert "consistency_score" in data
            assert "risk_assessment" in data
            assert "confidence" in data
            assert isinstance(data["major_factors"], list)
    finally:
        app.dependency_overrides.clear()
