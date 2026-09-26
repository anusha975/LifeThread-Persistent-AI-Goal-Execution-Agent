import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import app.db.session as db_session_module
import httpx
import pytest
from app.db.base import Base
from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.task import GoalDecomposition, Task, TaskDependency, TaskStatus
from mcp_server.client import MCPClient
from mcp_server.server import create_mcp_app
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

VALID_API_KEY = "lifethread-mcp-secret-key"


@pytest.fixture
async def setup_test_db() -> AsyncGenerator[async_sessionmaker, None]:
    """Provide isolated in-memory SQLite database wired to app.db.session."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    orig_engine = db_session_module._engine
    orig_factory = db_session_module._session_factory

    db_session_module._engine = test_engine
    db_session_module._session_factory = test_session_factory

    yield test_session_factory

    db_session_module._engine = orig_engine
    db_session_module._session_factory = orig_factory
    await test_engine.dispose()


@pytest.fixture
async def mcp_client(setup_test_db: Any) -> AsyncGenerator[MCPClient, None]:
    app = create_mcp_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        client = MCPClient(
            base_url="http://testserver",
            api_key=VALID_API_KEY,
            http_client=http_client,
        )
        yield client


async def seed_evaluation_goal(
    session_factory: async_sessionmaker,
    user_id: uuid.UUID,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Seed a goal with 3 tasks: Task 1 (COMPLETED), Task 2 (IN_PROGRESS), Task 3 (PENDING)."""
    async with session_factory() as session:
        goal = Goal(
            user_id=user_id,
            title="Production Evaluation Benchmark",
            objective="Deliver diagnostic performance analysis.",
            status=GoalStatus.ACTIVE,
            priority=GoalPriority.HIGH,
            deadline=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(goal)
        await session.flush()

        decomp = GoalDecomposition(
            goal_id=goal.id,
            version=1,
            is_active=True,
        )
        session.add(decomp)
        await session.flush()

        # Task 1: HIGH priority (weight 3), completed
        t1 = Task(
            goal_id=goal.id,
            version=1,
            title="Setup Infrastructure",
            status=TaskStatus.COMPLETED,
            priority=GoalPriority.HIGH,
            estimated_minutes=120,
            completed_at=datetime.now(UTC),
        )
        # Task 2: MEDIUM priority (weight 2), in progress
        t2 = Task(
            goal_id=goal.id,
            version=1,
            title="Implement Core Logic",
            status=TaskStatus.IN_PROGRESS,
            priority=GoalPriority.MEDIUM,
            estimated_minutes=180,
        )
        # Task 3: LOW priority (weight 1), pending
        t3 = Task(
            goal_id=goal.id,
            version=1,
            title="Deploy and Smoke Test",
            status=TaskStatus.PENDING,
            priority=GoalPriority.LOW,
            estimated_minutes=60,
        )
        session.add_all([t1, t2, t3])
        await session.flush()

        # t1 -> t2 -> t3
        dep1 = TaskDependency(
            task_id=t2.id, depends_on_task_id=t1.id, dependency_type="FINISH_TO_START"
        )
        dep2 = TaskDependency(
            task_id=t3.id, depends_on_task_id=t2.id, dependency_type="FINISH_TO_START"
        )
        session.add_all([dep1, dep2])
        await session.commit()

        return goal.id, [t1.id, t2.id, t3.id]


# ============================================================================
# TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_evaluation_tools_discovery(mcp_client: MCPClient) -> None:
    """Verify all 4 Evaluation MCP tools are discovered with structured schemas."""
    tools = await mcp_client.discover_tools()
    tool_names = [t["name"] for t in tools]

    expected = [
        "evaluate_progress",
        "evaluate_task",
        "identify_weakness",
        "calculate_goal_risk",
    ]
    for exp in expected:
        assert exp in tool_names, f"Tool {exp} should be discoverable via MCP"


@pytest.mark.asyncio
async def test_evaluate_progress_deterministic(
    mcp_client: MCPClient,
    setup_test_db: async_sessionmaker,
) -> None:
    """Verify evaluate_progress returns deterministic progress and deadline risk."""
    user_id = uuid.uuid4()
    goal_id, task_ids = await seed_evaluation_goal(setup_test_db, user_id)

    res = await mcp_client.call_tool(
        "evaluate_progress",
        {"goal_id": str(goal_id), "user_id": str(user_id)},
    )
    assert res["isError"] is False
    data = res["data"]

    # Total weight: 3 (t1) + 2 (t2) + 1 (t3) = 6
    # Earned: 3*1.0 (completed) + 2*0.25 (in_progress) = 3.5
    # Progress: 3.5 / 6 = 0.58
    assert data["goal_id"] == str(goal_id)
    assert data["goal_progress"] == 0.58
    assert data["raw_task_progress"] == 0.33  # 1/3
    assert data["total_tasks"] == 3
    assert data["completed_tasks"] == 1
    assert data["in_progress_tasks"] == 1
    assert data["pending_tasks"] == 1
    assert data["blocked_tasks"] == 0
    assert data["remaining_workload_minutes"] == 240  # 180 + 60
    assert data["deadline_risk"] in ("low", "medium")
    assert isinstance(data["weaknesses"], list)
    assert len(data["recommended_action"]) > 0


@pytest.mark.asyncio
async def test_evaluate_task_with_prerequisites_and_critical_path(
    mcp_client: MCPClient,
    setup_test_db: async_sessionmaker,
) -> None:
    """Verify evaluate_task identifies uncompleted prerequisites and critical path."""
    user_id = uuid.uuid4()
    goal_id, task_ids = await seed_evaluation_goal(setup_test_db, user_id)
    t1_id, t2_id, t3_id = task_ids

    # Evaluate Task 3 (depends on Task 2, which is IN_PROGRESS)
    res_t3 = await mcp_client.call_tool(
        "evaluate_task",
        {"task_id": str(t3_id), "user_id": str(user_id)},
    )
    assert res_t3["isError"] is False
    t3_eval = res_t3["data"]
    assert t3_eval["task_id"] == str(t3_id)
    assert t3_eval["is_blocked_by_prerequisites"] is True
    assert len(t3_eval["uncompleted_prerequisites"]) == 1
    assert t3_eval["uncompleted_prerequisites"][0]["task_id"] == str(t2_id)
    assert t3_eval["is_on_critical_path"] is True
    assert t3_eval["status"] == TaskStatus.PENDING.value

    # Evaluate Task 1 (COMPLETED)
    res_t1 = await mcp_client.call_tool(
        "evaluate_task",
        {"task_id": str(t1_id), "user_id": str(user_id)},
    )
    assert res_t1["isError"] is False
    t1_eval = res_t1["data"]
    assert t1_eval["status"] == TaskStatus.COMPLETED.value
    assert t1_eval["is_blocked_by_prerequisites"] is False
    assert t1_eval["risk_level"] == "low"
    assert "completed successfully" in t1_eval["recommended_action"].lower()


@pytest.mark.asyncio
async def test_identify_weakness_detects_blockers_and_overdue(
    mcp_client: MCPClient,
    setup_test_db: async_sessionmaker,
) -> None:
    """Verify identify_weakness identifies blocked, overdue, and bottleneck tasks."""
    user_id = uuid.uuid4()
    async with setup_test_db() as session:
        goal = Goal(
            user_id=user_id,
            title="Troubled Project with Blockers",
            objective="Analyze vulnerabilities",
            status=GoalStatus.ACTIVE,
            priority=GoalPriority.CRITICAL,
            deadline=datetime.now(UTC) + timedelta(days=2),
        )
        session.add(goal)
        await session.flush()

        decomp = GoalDecomposition(goal_id=goal.id, version=1, is_active=True)
        session.add(decomp)
        await session.flush()

        # Task A: BLOCKED
        t_a = Task(
            goal_id=goal.id,
            version=1,
            title="Database Provisioning",
            status=TaskStatus.BLOCKED,
            priority=GoalPriority.CRITICAL,
            estimated_minutes=120,
        )
        # Task B: Overdue
        t_b = Task(
            goal_id=goal.id,
            version=1,
            title="API Design",
            status=TaskStatus.PENDING,
            priority=GoalPriority.HIGH,
            estimated_minutes=90,
            due_at=datetime.now(UTC) - timedelta(hours=5),
        )
        # Task C: Cancelled / Failure
        t_c = Task(
            goal_id=goal.id,
            version=1,
            title="Legacy Integration",
            status=TaskStatus.CANCELLED,
            priority=GoalPriority.LOW,
            estimated_minutes=60,
        )
        session.add_all([t_a, t_b, t_c])
        await session.flush()

        # Downstream tasks depending on A (making A a bottleneck)
        t_d1 = Task(
            goal_id=goal.id,
            version=1,
            title="Service 1",
            status=TaskStatus.PENDING,
            estimated_minutes=60,
        )
        t_d2 = Task(
            goal_id=goal.id,
            version=1,
            title="Service 2",
            status=TaskStatus.PENDING,
            estimated_minutes=60,
        )
        session.add_all([t_d1, t_d2])
        await session.flush()

        dep1 = TaskDependency(
            task_id=t_d1.id, depends_on_task_id=t_a.id, dependency_type="FINISH_TO_START"
        )
        dep2 = TaskDependency(
            task_id=t_d2.id, depends_on_task_id=t_a.id, dependency_type="FINISH_TO_START"
        )
        session.add_all([dep1, dep2])
        await session.commit()
        goal_id = goal.id

    res = await mcp_client.call_tool(
        "identify_weakness",
        {"goal_id": str(goal_id), "user_id": str(user_id)},
    )
    assert res["isError"] is False
    data = res["data"]

    categories = [w["category"] for w in data["weaknesses"]]
    assert "BLOCKED_EXECUTION" in categories
    assert "OVERDUE_TASK" in categories
    assert "RECENT_FAILURE" in categories
    assert "DEPENDENCY_BOTTLENECK" in categories
    assert data["overall_health"] in ("CRITICAL", "AT_RISK")
    assert data["weakness_count"] >= 3
    assert len(data["recommended_action"]) > 0


@pytest.mark.asyncio
async def test_calculate_goal_risk_deterministic(
    mcp_client: MCPClient,
    setup_test_db: async_sessionmaker,
) -> None:
    """Verify calculate_goal_risk scores across schedule, dependency, and priority risks."""
    user_id = uuid.uuid4()
    goal_id, task_ids = await seed_evaluation_goal(setup_test_db, user_id)

    res = await mcp_client.call_tool(
        "calculate_goal_risk",
        {"goal_id": str(goal_id), "user_id": str(user_id)},
    )
    assert res["isError"] is False
    risk = res["data"]

    assert risk["goal_id"] == str(goal_id)
    assert 0.0 <= risk["composite_risk_score"] <= 1.0
    assert risk["deadline_risk"] in ("low", "medium", "high", "critical")
    assert 0.0 <= risk["schedule_risk_score"] <= 1.0
    assert 0.0 <= risk["dependency_risk_score"] <= 1.0
    assert 0.0 <= risk["priority_risk_score"] <= 1.0
    assert len(risk["recommended_action"]) > 0


@pytest.mark.asyncio
async def test_evaluation_tools_multi_tenant_isolation(
    mcp_client: MCPClient,
    setup_test_db: async_sessionmaker,
) -> None:
    """Requirement: Cross-tenant evaluation requests must be rejected with NOT_FOUND."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    goal_id, task_ids = await seed_evaluation_goal(setup_test_db, user_a)
    task_id = task_ids[0]

    # User B cannot evaluate User A's goal progress
    p_res = await mcp_client.call_tool(
        "evaluate_progress",
        {"goal_id": str(goal_id), "user_id": str(user_b)},
    )
    assert p_res["isError"] is True
    assert "not found" in str(p_res["data"]).lower()

    # User B cannot evaluate User A's task
    t_res = await mcp_client.call_tool(
        "evaluate_task",
        {"task_id": str(task_id), "user_id": str(user_b)},
    )
    assert t_res["isError"] is True
    assert "not found" in str(t_res["data"]).lower()

    # User B cannot identify weaknesses on User A's goal
    w_res = await mcp_client.call_tool(
        "identify_weakness",
        {"goal_id": str(goal_id), "user_id": str(user_b)},
    )
    assert w_res["isError"] is True
    assert "not found" in str(w_res["data"]).lower()

    # User B cannot calculate risk on User A's goal
    r_res = await mcp_client.call_tool(
        "calculate_goal_risk",
        {"goal_id": str(goal_id), "user_id": str(user_b)},
    )
    assert r_res["isError"] is True
    assert "not found" in str(r_res["data"]).lower()
