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
from mcp_server.client import MCPClient, MCPClientError
from mcp_server.schemas import JSONRPCErrorCode
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


async def seed_decomposed_goal(
    session_factory: async_sessionmaker,
    user_id: uuid.UUID,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Seed a goal with an active decomposition and 3 dependent tasks."""
    async with session_factory() as session:
        goal = Goal(
            user_id=user_id,
            title="Build Production RAG Pipeline",
            objective="Architect and deploy low-latency semantic search.",
            status=GoalStatus.ACTIVE,
            priority=GoalPriority.HIGH,
            deadline=datetime.now(UTC) + timedelta(days=14),
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

        task1 = Task(
            goal_id=goal.id,
            version=1,
            title="Setup Vector Database",
            description="Deploy Qdrant cluster",
            status=TaskStatus.PENDING,
            priority=GoalPriority.HIGH,
            estimated_minutes=120,
        )
        task2 = Task(
            goal_id=goal.id,
            version=1,
            title="Implement Embedding Pipeline",
            description="Batch chunking and embedding",
            status=TaskStatus.PENDING,
            priority=GoalPriority.HIGH,
            estimated_minutes=180,
        )
        task3 = Task(
            goal_id=goal.id,
            version=1,
            title="Setup Reranking & Evaluation",
            description="Cross-encoder reranking",
            status=TaskStatus.PENDING,
            priority=GoalPriority.MEDIUM,
            estimated_minutes=90,
        )
        session.add_all([task1, task2, task3])
        await session.flush()

        # Task 1 -> Task 2 -> Task 3
        dep1 = TaskDependency(
            task_id=task2.id,
            depends_on_task_id=task1.id,
            dependency_type="FINISH_TO_START",
        )
        dep2 = TaskDependency(
            task_id=task3.id,
            depends_on_task_id=task2.id,
            dependency_type="FINISH_TO_START",
        )
        session.add_all([dep1, dep2])
        await session.commit()

        return goal.id, [task1.id, task2.id, task3.id]


# ============================================================================
# TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_planning_tools_discovery(mcp_client: MCPClient) -> None:
    """Verify all 5 planning tools are discoverable via MCP."""
    tools = await mcp_client.discover_tools()
    tool_names = [t["name"] for t in tools]

    expected = [
        "generate_plan",
        "get_plan",
        "replan_preview",
        "update_task",
        "prioritize_task",
    ]
    for exp in expected:
        assert exp in tool_names, f"Tool '{exp}' not discovered in {tool_names}"


@pytest.mark.asyncio
async def test_generate_and_get_plan_with_versioning(
    mcp_client: MCPClient,
    setup_test_db: async_sessionmaker,
) -> None:
    """Verify generate_plan creates a plan, get_plan retrieves it, and generating again preserves versions."""
    user_id = uuid.uuid4()
    goal_id, _ = await seed_decomposed_goal(setup_test_db, user_id)

    # 1. Generate plan v1
    gen_res = await mcp_client.call_tool(
        "generate_plan",
        {
            "goal_id": str(goal_id),
            "user_id": str(user_id),
            "daily_available_hours": 4.0,
            "reason": "Initial engineering plan",
        },
    )
    assert gen_res["isError"] is False
    plan_v1 = gen_res["data"]
    assert plan_v1["version"] == 1
    assert plan_v1["status"] == "ACTIVE"
    assert plan_v1["is_feasible"] is True
    assert len(plan_v1["items"]) == 3
    assert plan_v1["total_duration_minutes"] == 390

    # 2. Get active plan
    get_res = await mcp_client.call_tool(
        "get_plan",
        {"goal_id": str(goal_id), "user_id": str(user_id)},
    )
    assert get_res["isError"] is False
    assert get_res["data"]["version"] == 1

    # 3. Generate plan v2 (revision)
    gen_v2_res = await mcp_client.call_tool(
        "generate_plan",
        {
            "goal_id": str(goal_id),
            "user_id": str(user_id),
            "daily_available_hours": 6.0,
            "reason": "Increased working capacity",
        },
    )
    assert gen_v2_res["isError"] is False
    assert gen_v2_res["data"]["version"] == 2

    # 4. Verify historical version 1 is preserved
    hist_res = await mcp_client.call_tool(
        "get_plan",
        {"goal_id": str(goal_id), "user_id": str(user_id), "version": 1},
    )
    assert hist_res["isError"] is False
    assert hist_res["data"]["version"] == 1
    assert hist_res["data"]["status"] == "SUPERSEDED"


@pytest.mark.asyncio
async def test_replan_preview_calculates_without_committing(
    mcp_client: MCPClient,
    setup_test_db: async_sessionmaker,
) -> None:
    """Acceptance Criteria: replan_preview calculates proposed change without committing to database."""
    user_id = uuid.uuid4()
    goal_id, task_ids = await seed_decomposed_goal(setup_test_db, user_id)

    # Initial plan v1
    await mcp_client.call_tool(
        "generate_plan",
        {"goal_id": str(goal_id), "user_id": str(user_id), "daily_available_hours": 4.0},
    )

    # Replan preview with hypothetical task estimate change
    preview_res = await mcp_client.call_tool(
        "replan_preview",
        {
            "goal_id": str(goal_id),
            "user_id": str(user_id),
            "daily_available_hours": 2.0,  # restricted capacity
            "hypothetical_task_estimates": {str(task_ids[0]): 360},  # task 1 takes 6 hours
            "reason": "Simulating scope increase with reduced hours",
        },
    )
    assert preview_res["isError"] is False
    preview = preview_res["data"]

    # Verify dry run flags
    assert preview["is_committed"] is False
    assert preview["proposed_total_duration_minutes"] == 630  # 360 + 180 + 90
    assert len(preview["proposed_items"]) == 3
    assert "Uncommitted dry run" in preview["summary"]

    # Verify active plan in database was NOT modified
    active_plan = await mcp_client.call_tool(
        "get_plan",
        {"goal_id": str(goal_id), "user_id": str(user_id)},
    )
    assert active_plan["data"]["version"] == 1
    assert active_plan["data"]["total_duration_minutes"] == 390  # Still 390, not 630!


@pytest.mark.asyncio
async def test_update_and_prioritize_task(
    mcp_client: MCPClient,
    setup_test_db: async_sessionmaker,
) -> None:
    """Verify update_task and prioritize_task MCP tools."""
    user_id = uuid.uuid4()
    goal_id, task_ids = await seed_decomposed_goal(setup_test_db, user_id)
    target_task_id = task_ids[0]

    # 1. Update task
    update_res = await mcp_client.call_tool(
        "update_task",
        {
            "task_id": str(target_task_id),
            "goal_id": str(goal_id),
            "user_id": str(user_id),
            "title": "Setup Managed Vector DB Cluster",
            "estimated_minutes": 150,
        },
    )
    assert update_res["isError"] is False
    assert update_res["data"]["title"] == "Setup Managed Vector DB Cluster"
    assert update_res["data"]["estimated_minutes"] == 150

    # 2. Prioritize task
    prio_res = await mcp_client.call_tool(
        "prioritize_task",
        {
            "task_id": str(target_task_id),
            "goal_id": str(goal_id),
            "user_id": str(user_id),
            "priority": "CRITICAL",
            "reason": "Blocking core indexing architecture",
        },
    )
    assert prio_res["isError"] is False
    assert prio_res["data"]["priority"] == "CRITICAL"


@pytest.mark.asyncio
async def test_planning_multi_tenant_isolation(
    mcp_client: MCPClient,
    setup_test_db: async_sessionmaker,
) -> None:
    """Verify cross-tenant security: User B cannot access or modify User A's plan or tasks."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    goal_id, task_ids = await seed_decomposed_goal(setup_test_db, user_a)

    await mcp_client.call_tool(
        "generate_plan",
        {"goal_id": str(goal_id), "user_id": str(user_a)},
    )

    # User B attempts get_plan
    get_b = await mcp_client.call_tool(
        "get_plan",
        {"goal_id": str(goal_id), "user_id": str(user_b)},
    )
    assert get_b["isError"] is True
    assert "not found or access denied" in get_b["data"].lower()

    # User B attempts update_task
    update_b = await mcp_client.call_tool(
        "update_task",
        {
            "task_id": str(task_ids[0]),
            "goal_id": str(goal_id),
            "user_id": str(user_b),
            "title": "Malicious Update",
        },
    )
    assert update_b["isError"] is True
    assert "not found or access denied" in update_b["data"].lower()


@pytest.mark.asyncio
async def test_generate_plan_validation_error(mcp_client: MCPClient) -> None:
    """Verify input validation rejects illegal parameters (e.g. daily hours > 24)."""
    user_id = str(uuid.uuid4())
    goal_id = str(uuid.uuid4())

    with pytest.raises(MCPClientError) as exc_info:
        await mcp_client.call_tool(
            "generate_plan",
            {
                "goal_id": goal_id,
                "user_id": user_id,
                "daily_available_hours": 30.0,  # Invalid: > 24
            },
        )
    assert exc_info.value.code == JSONRPCErrorCode.INVALID_PARAMS.value
