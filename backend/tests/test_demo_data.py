"""Module 46: Demo Data and Example Scenarios Test Suite.

Verifies:
1. Safe development/demo dataset creation separated from production data.
2. Production safeguards: disallowed when ENVIRONMENT=production or ALLOW_DEMO_DATA=False.
3. Realistic long-running goals demonstrating all 6 criteria:
   - changing deadlines (compressed deadline, replan diff, elevated risk)
   - limited available time (daily capacity budget, deterministic slot scheduling)
   - task failure (failed/cancelled task with agent diagnostic trace and recovery loop)
   - newly discovered weakness (continuous learning loop, "Learned weakness" memory vector, remedial drill task)
   - blocked dependency (directed acyclic graph with BLOCKS edge and BLOCKED task status)
   - successful completion (100% completion, all milestones and tasks completed, past outcome memory)
4. Clean separation from production logic (no hard-coded scenarios in production path).
5. Fast reset, loading, and status inspection via DemoDataLoader and REST API.
"""

import uuid
from unittest.mock import patch

import pytest
from app.db.base import Base
from app.db.models.goal import (
    Goal,
    GoalConstraint,
    GoalMilestone,
    GoalPriority,
    GoalStatus,
    MilestoneStatus,
)
from app.db.models.memory import Memory, MemoryType
from app.db.models.plan import Plan, PlanItem, PlanStatus
from app.db.models.task import Task, TaskDependency, TaskStatus
from app.db.models.user import User
from app.demo.loader import DemoDataLoader
from app.demo.scenarios import (
    DEMO_USER_EMAIL,
    DEMO_USER_NAME,
)
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
async def async_engine():
    """Isolated in-memory SQLite engine for demo data test suite."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(async_engine):
    return async_sessionmaker(bind=async_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def regular_user(db_session: AsyncSession) -> User:
    """Non-demo user to ensure tenant isolation during demo resets and loading."""
    user = User(
        id=uuid.uuid4(),
        email="real_user@production-company.com",
        password_hash="hashed_prod_pass",
        display_name="Real Production User",
        timezone="UTC",
        is_active=True,
    )
    db_session.add(user)
    # Add a real goal that must NEVER be touched by demo reset
    real_goal = Goal(
        id=uuid.uuid4(),
        user_id=user.id,
        title="Real Critical Production Goal",
        objective="Do not wipe me under any circumstances",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.CRITICAL,
    )
    db_session.add(real_goal)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def api_client(session_factory):
    """HTTP client configured with DB session override."""
    async def override_get_db():
        async with session_factory() as session:
            yield session

    from app.db.session import get_db
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.clear()


# =============================================================================
# TEST SUITE: DEMO DATA SAFETY & GUARDS
# =============================================================================


@pytest.mark.asyncio
async def test_demo_safety_guard_production():
    """Demo loader must raise PermissionError if environment is production or allow_demo=False."""
    with patch("app.demo.loader.get_settings") as mock_settings:
        # Case 1: Environment is production
        mock_settings.return_value.ENVIRONMENT = "production"
        mock_settings.return_value.ALLOW_DEMO_DATA = True
        assert DemoDataLoader.is_demo_allowed() is False

        # Case 2: ALLOW_DEMO_DATA is False
        mock_settings.return_value.ENVIRONMENT = "development"
        mock_settings.return_value.ALLOW_DEMO_DATA = False
        assert DemoDataLoader.is_demo_allowed() is False

        # Case 3: Allowed in non-production with ALLOW_DEMO_DATA=True
        mock_settings.return_value.ENVIRONMENT = "development"
        mock_settings.return_value.ALLOW_DEMO_DATA = True
        assert DemoDataLoader.is_demo_allowed() is True


@pytest.mark.asyncio
async def test_demo_safety_guard_blocks_execution(db_session: AsyncSession):
    """Calling loader or clear when disallowed must raise PermissionError."""
    with patch.object(DemoDataLoader, "is_demo_allowed", return_value=False):
        with pytest.raises(PermissionError, match="disabled in production"):
            await DemoDataLoader.load_demo_scenarios(db_session)

        with pytest.raises(PermissionError, match="disabled in production"):
            await DemoDataLoader.clear_demo_data(db_session)


# =============================================================================
# TEST SUITE: DEMO USER LIFECYCLE & TENANT ISOLATION
# =============================================================================


@pytest.mark.asyncio
async def test_demo_user_get_or_create(db_session: AsyncSession):
    """DemoDataLoader creates dedicated demo@lifethread.ai user idempotently."""
    user1 = await DemoDataLoader.get_or_create_demo_user(db_session)
    assert user1.email == DEMO_USER_EMAIL
    assert user1.display_name == DEMO_USER_NAME
    assert user1.is_active is True

    # Idempotent call returns same user
    user2 = await DemoDataLoader.get_or_create_demo_user(db_session)
    assert user1.id == user2.id


@pytest.mark.asyncio
async def test_demo_clear_preserves_real_users(db_session: AsyncSession, regular_user: User):
    """Clearing demo data removes ONLY demo data and preserves real users/goals."""
    demo_user = await DemoDataLoader.get_or_create_demo_user(db_session)
    await DemoDataLoader.load_demo_scenarios(db_session, target_user=demo_user)

    # Verify demo data exists
    demo_status_before = await DemoDataLoader.get_demo_status(db_session, target_user_id=demo_user.id)
    assert demo_status_before["goals_count"] == 6

    # Verify regular user has their goal
    reg_goals_before = (
        await db_session.execute(select(Goal).where(Goal.user_id == regular_user.id))
    ).scalars().all()
    assert len(reg_goals_before) == 1

    # Clear demo data
    clear_result = await DemoDataLoader.clear_demo_data(db_session, target_user_id=demo_user.id)
    assert clear_result["goals_deleted"] == 6
    assert clear_result["memories_deleted"] > 0

    # Ensure regular user still intact
    reg_goals_after = (
        await db_session.execute(select(Goal).where(Goal.user_id == regular_user.id))
    ).scalars().all()
    assert len(reg_goals_after) == 1
    assert reg_goals_after[0].title == "Real Critical Production Goal"


# =============================================================================
# TEST SUITE: ALL 6 REALISTIC SCENARIOS VERIFICATION
# =============================================================================


@pytest.mark.asyncio
async def test_load_all_six_scenarios_comprehensive(db_session: AsyncSession):
    """Load all 6 realistic scenarios and assert every single acceptance criterion is satisfied."""
    demo_user = await DemoDataLoader.get_or_create_demo_user(db_session)
    load_summary = await DemoDataLoader.load_demo_scenarios(db_session, target_user=demo_user)

    assert load_summary["success"] is True
    assert load_summary["goals_created"] == 6
    assert load_summary["tasks_created"] >= 18
    assert load_summary["plans_created"] >= 6
    assert load_summary["memories_created"] >= 6
    assert load_summary["dependencies_created"] >= 2

    # Fetch all goals created for demo user
    goals_res = await db_session.execute(
        select(Goal).where(Goal.user_id == demo_user.id).order_by(Goal.created_at)
    )
    goals = goals_res.scalars().all()
    assert len(goals) == 6

    # Build a lookup by title keyword
    g1 = next((g for g in goals if "SOC2 Type II" in g.title), None)
    g2 = next((g for g in goals if "Financial Ledger" in g.title), None)
    g3 = next((g for g in goals if "Database Migration" in g.title), None)
    g4 = next((g for g in goals if "Rust Systems Programming" in g.title), None)
    g5 = next((g for g in goals if "Service Mesh" in g.title), None)
    g6 = next((g for g in goals if "pgvector Semantic RAG" in g.title), None)
    assert g1 is not None, "Scenario 1 (changing deadlines) must exist"
    assert "SOC2 Type II" in g1.title
    assert g1.priority == GoalPriority.CRITICAL

    # Verify deadline constraints
    constraints_g1 = (
        await db_session.execute(select(GoalConstraint).where(GoalConstraint.goal_id == g1.id))
    ).scalars().all()
    assert len(constraints_g1) >= 1
    deadline_c = next((c for c in constraints_g1 if "deadline" in c.type), None)
    assert deadline_c is not None
    assert deadline_c.metadata_.get("compressed") is True
    assert deadline_c.metadata_.get("revised_deadline_days") == 12

    # Verify Plan v1 and Plan v2 exist with replanning diff
    plans_g1 = (
        await db_session.execute(
            select(Plan).where(Plan.goal_id == g1.id).order_by(Plan.version)
        )
    ).scalars().all()
    assert len(plans_g1) >= 2
    p1, p2 = plans_g1[0], plans_g1[1]
    assert p1.version == 1 and p1.status == PlanStatus.SUPERSEDED
    assert p2.version == 2 and p2.status == PlanStatus.ACTIVE
    assert p1.deadline_risk < p2.deadline_risk  # Risk elevated after compression
    assert p2.risk_level == "HIGH"

    # Verify PlanItems were generated
    items_p2 = (
        await db_session.execute(select(PlanItem).where(PlanItem.plan_id == p2.id))
    ).scalars().all()
    assert len(items_p2) >= 3

    # -------------------------------------------------------------------------
    # 2. SCENARIO 2: Limited Available Time (Real-Time Financial Ledger)
    # -------------------------------------------------------------------------
    assert g2 is not None, "Scenario 2 (limited available time) must exist"
    assert "Financial Ledger" in g2.title

    # Verify capacity constraint
    constraints_g2 = (
        await db_session.execute(select(GoalConstraint).where(GoalConstraint.goal_id == g2.id))
    ).scalars().all()
    capacity_c = next((c for c in constraints_g2 if "capacity" in c.type), None)
    assert capacity_c is not None
    assert capacity_c.metadata_.get("daily_budget_minutes") == 90

    # Verify tasks respect limited time slots (no task exceeds 90 minutes)
    tasks_g2 = (
        await db_session.execute(select(Task).where(Task.goal_id == g2.id))
    ).scalars().all()
    assert len(tasks_g2) >= 3
    for t in tasks_g2:
        assert t.estimated_minutes <= 90, f"Task {t.title} exceeds daily 90m budget"

    # -------------------------------------------------------------------------
    # 3. SCENARIO 3: Task Failure & Diagnostic Recovery (Database Migration)
    # -------------------------------------------------------------------------
    assert g3 is not None, "Scenario 3 (task failure) must exist"
    assert "Database Migration" in g3.title

    tasks_g3 = (
        await db_session.execute(select(Task).where(Task.goal_id == g3.id))
    ).scalars().all()
    failed_task = next((t for t in tasks_g3 if t.status == TaskStatus.CANCELLED), None)
    assert failed_task is not None, "Scenario 3 must contain a failed/interrupted task"
    assert "pglogical replication stream" in failed_task.title

    # Diagnostic memory exists documenting failure and recovery
    mems_g3 = (
        await db_session.execute(select(Memory).where(Memory.user_id == demo_user.id))
    ).scalars().all()
    failure_mem = next(
        (m for m in mems_g3 if "IOPS" in m.content or "failed with" in m.content),
        None,
    )
    assert failure_mem is not None, "Scenario 3 must contain failure diagnostic memory"

    # -------------------------------------------------------------------------
    # 4. SCENARIO 4: Newly Discovered Weakness (Continuous Learning Loop)
    # -------------------------------------------------------------------------
    assert g4 is not None, "Scenario 4 (newly discovered weakness) must exist"
    assert "Rust Systems Programming" in g4.title

    # Verify "Learned weakness" memory exists with vector embedding
    mems_g4 = (
        await db_session.execute(select(Memory).where(Memory.user_id == demo_user.id))
    ).scalars().all()
    weakness_mem = next(
        (m for m in mems_g4 if m.metadata_json.get("category") == "Learned weakness"),
        None,
    )
    assert weakness_mem is not None, "Scenario 4 must contain a Learned weakness memory"
    assert weakness_mem.memory_type == MemoryType.SEMANTIC
    assert "pin projection" in weakness_mem.content.lower()
    assert weakness_mem.embedding is not None
    assert len(weakness_mem.embedding) == 1536

    # Verify remedial drill task was generated from learning loop
    tasks_g4 = (
        await db_session.execute(select(Task).where(Task.goal_id == g4.id))
    ).scalars().all()
    drill_task = next(
        (t for t in tasks_g4 if "Drill Exercise" in t.title or "Pin projection" in t.title),
        None,
    )
    assert drill_task is not None, "Scenario 4 must contain a remedial drill task spawned by weakness"

    # -------------------------------------------------------------------------
    # 5. SCENARIO 5: Blocked Dependency DAG (Service Mesh Deployment)
    # -------------------------------------------------------------------------
    assert g5 is not None, "Scenario 5 (blocked dependency) must exist"
    assert "Service Mesh" in g5.title

    tasks_g5 = (
        await db_session.execute(select(Task).where(Task.goal_id == g5.id))
    ).scalars().all()
    blocked_task = next((t for t in tasks_g5 if t.status == TaskStatus.BLOCKED), None)
    assert blocked_task is not None, "Scenario 5 must contain a BLOCKED task"
    assert "Configure Istio Ingress Gateway" in blocked_task.title

    # Verify TaskDependency edge exists with BLOCKS
    deps_g5 = (
        await db_session.execute(
            select(TaskDependency).where(TaskDependency.task_id == blocked_task.id)
        )
    ).scalars().all()
    assert len(deps_g5) >= 1
    assert deps_g5[0].dependency_type == "BLOCKS"

    # -------------------------------------------------------------------------
    # 6. SCENARIO 6: Successful Goal Completion (pgvector Semantic Engine)
    # -------------------------------------------------------------------------
    assert g6 is not None, "Scenario 6 (successful completion) must exist"
    assert "pgvector Semantic RAG" in g6.title
    assert g6.status == GoalStatus.COMPLETED

    # 100% of tasks must be COMPLETED
    tasks_g6 = (
        await db_session.execute(select(Task).where(Task.goal_id == g6.id))
    ).scalars().all()
    assert len(tasks_g6) >= 3
    for t in tasks_g6:
        assert t.status == TaskStatus.COMPLETED, f"Task {t.title} should be COMPLETED"

    # 100% of milestones must be COMPLETED
    milestones_g6 = (
        await db_session.execute(select(GoalMilestone).where(GoalMilestone.goal_id == g6.id))
    ).scalars().all()
    assert len(milestones_g6) >= 3
    for m in milestones_g6:
        assert m.status == MilestoneStatus.COMPLETED, f"Milestone {m.title} should be COMPLETED"

    # Outcome memory exists
    mems_all = (
        await db_session.execute(select(Memory).where(Memory.user_id == demo_user.id))
    ).scalars().all()
    outcome_mem = next(
        (m for m in mems_all if "Semantic pgvector indexing achieved" in m.content),
        None,
    )
    assert outcome_mem is not None, "Scenario 6 must produce an outcome memory"
    assert outcome_mem.importance_score >= 0.9


# =============================================================================
# TEST SUITE: DEMO STATUS AND REST API
# =============================================================================


@pytest.mark.asyncio
async def test_demo_status_inspection(db_session: AsyncSession):
    """Demo status correctly reflects loaded vs cleared state."""
    demo_user = await DemoDataLoader.get_or_create_demo_user(db_session)

    # Empty initially
    status_0 = await DemoDataLoader.get_demo_status(db_session, target_user_id=demo_user.id)
    assert status_0["is_loaded"] is False
    assert status_0["goals_count"] == 0

    # After loading
    await DemoDataLoader.load_demo_scenarios(db_session, target_user=demo_user)
    status_1 = await DemoDataLoader.get_demo_status(db_session, target_user_id=demo_user.id)
    assert status_1["is_loaded"] is True
    assert status_1["goals_count"] == 6
    assert status_1["memories_count"] >= 6


@pytest.mark.asyncio
async def test_demo_rest_api_lifecycle(api_client: AsyncClient):
    """Verify REST API /api/v1/demo endpoints: status -> load -> reset."""
    # 1. Check initial status
    resp = await api_client.get("/api/v1/demo/status")
    assert resp.status_code == 200
    status_data = resp.json()
    assert "is_loaded" in status_data
    assert status_data["environment_allowed"] is True

    # 2. Trigger demo load via API
    load_resp = await api_client.post("/api/v1/demo/load", json={"reset_existing": True})
    assert load_resp.status_code == 201
    load_data = load_resp.json()
    assert load_data["success"] is True
    assert load_data["goals_created"] == 6
    assert len(load_data["scenarios"]) == 6
    assert load_data["user_email"] == DEMO_USER_EMAIL

    # 3. Check status again
    status_resp = await api_client.get("/api/v1/demo/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["is_loaded"] is True
    assert status_resp.json()["goals_count"] == 6

    # 4. Reset demo data via API
    reset_resp = await api_client.post("/api/v1/demo/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["success"] is True
    assert reset_resp.json()["goals_deleted"] == 6

    # 5. Verify status is reset
    final_status = await api_client.get("/api/v1/demo/status")
    assert final_status.status_code == 200
    assert final_status.json()["is_loaded"] is False
    assert final_status.json()["goals_count"] == 0
