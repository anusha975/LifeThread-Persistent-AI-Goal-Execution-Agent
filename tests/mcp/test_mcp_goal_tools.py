import uuid
from collections.abc import AsyncGenerator
from typing import Any

import app.db.session as db_session_module
import httpx
import pytest
from app.db.base import Base
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


# ============================================================================
# TESTS: CALLING EVERY GOAL MCP TOOL VIA MCP CLIENT
# ============================================================================


@pytest.mark.asyncio
async def test_mcp_goal_tools_discovery(mcp_client: MCPClient) -> None:
    """Verify all 6 Goal Engine MCP tools are discovered with structured schemas."""
    tools = await mcp_client.discover_tools()
    tool_names = [t["name"] for t in tools]

    expected_tools = [
        "create_goal",
        "get_goal",
        "update_goal",
        "pause_goal",
        "resume_goal",
        "complete_goal",
    ]
    for expected in expected_tools:
        assert expected in tool_names, (
            f"Tool '{expected}' not in discovered MCP tools: {tool_names}"
        )

    # Verify input schema of create_goal
    create_tool = next(t for t in tools if t["name"] == "create_goal")
    assert "properties" in create_tool["inputSchema"]
    assert "title" in create_tool["inputSchema"]["properties"]
    assert "objective" in create_tool["inputSchema"]["properties"]
    assert "user_id" in create_tool["inputSchema"]["properties"]


@pytest.mark.asyncio
async def test_mcp_create_and_get_goal(mcp_client: MCPClient) -> None:
    """Verify create_goal and get_goal through external MCP client."""
    user_id = str(uuid.uuid4())

    # 1. create_goal
    create_args = {
        "user_id": user_id,
        "title": "Master Quantum Computing",
        "objective": "Complete quantum algorithms coursework and build a simulator.",
        "description": "Quarterly deep-dive engineering goal.",
        "priority": "HIGH",
        "success_criteria": ["Finish 5 problem sets", "Simulate Shor's algorithm"],
        "constraints": [{"type": "budget", "value": "under $200"}],
        "milestones": [{"title": "Basics & Linear Algebra", "order_index": 1}],
    }

    create_res = await mcp_client.call_tool("create_goal", create_args)
    assert create_res["isError"] is False
    goal_data = create_res["data"]
    assert goal_data["title"] == "Master Quantum Computing"
    assert goal_data["status"] == "ACTIVE"
    assert goal_data["priority"] == "HIGH"
    assert goal_data["user_id"] == user_id
    assert len(goal_data["success_criteria"]) == 2
    assert len(goal_data["constraints"]) == 1
    assert len(goal_data["milestones"]) == 1

    goal_id = goal_data["id"]

    # 2. get_goal
    get_res = await mcp_client.call_tool(
        "get_goal",
        {"goal_id": goal_id, "user_id": user_id},
    )
    assert get_res["isError"] is False
    retrieved_data = get_res["data"]
    assert retrieved_data["id"] == goal_id
    assert retrieved_data["title"] == "Master Quantum Computing"
    assert retrieved_data["user_id"] == user_id


@pytest.mark.asyncio
async def test_mcp_update_goal(mcp_client: MCPClient) -> None:
    """Verify update_goal through external MCP client."""
    user_id = str(uuid.uuid4())

    # Create initial goal
    create_res = await mcp_client.call_tool(
        "create_goal",
        {
            "user_id": user_id,
            "title": "Initial Goal Title",
            "objective": "Initial objective details",
        },
    )
    goal_id = create_res["data"]["id"]

    # Update goal
    update_res = await mcp_client.call_tool(
        "update_goal",
        {
            "goal_id": goal_id,
            "user_id": user_id,
            "title": "Updated Goal Title",
            "priority": "CRITICAL",
        },
    )
    assert update_res["isError"] is False
    updated_data = update_res["data"]
    assert updated_data["id"] == goal_id
    assert updated_data["title"] == "Updated Goal Title"
    assert updated_data["priority"] == "CRITICAL"


@pytest.mark.asyncio
async def test_mcp_pause_and_resume_goal(mcp_client: MCPClient) -> None:
    """Verify pause_goal and resume_goal through external MCP client."""
    user_id = str(uuid.uuid4())

    # Create initial active goal
    create_res = await mcp_client.call_tool(
        "create_goal",
        {
            "user_id": user_id,
            "title": "Pausable Goal",
            "objective": "Testing pause and resume via MCP",
        },
    )
    goal_id = create_res["data"]["id"]
    assert create_res["data"]["status"] == "ACTIVE"

    # Pause goal
    pause_res = await mcp_client.call_tool(
        "pause_goal",
        {"goal_id": goal_id, "user_id": user_id},
    )
    assert pause_res["isError"] is False
    assert pause_res["data"]["status"] == "PAUSED"

    # Resume goal
    resume_res = await mcp_client.call_tool(
        "resume_goal",
        {"goal_id": goal_id, "user_id": user_id},
    )
    assert resume_res["isError"] is False
    assert resume_res["data"]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_mcp_complete_goal(mcp_client: MCPClient) -> None:
    """Verify complete_goal through external MCP client."""
    user_id = str(uuid.uuid4())

    create_res = await mcp_client.call_tool(
        "create_goal",
        {
            "user_id": user_id,
            "title": "Completable Goal",
            "objective": "Testing completion lifecycle via MCP",
        },
    )
    goal_id = create_res["data"]["id"]

    # Complete goal
    complete_res = await mcp_client.call_tool(
        "complete_goal",
        {"goal_id": goal_id, "user_id": user_id},
    )
    assert complete_res["isError"] is False
    assert complete_res["data"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_mcp_multi_tenant_isolation(mcp_client: MCPClient) -> None:
    """Requirement: Never expose another user's goal (strict tenant isolation)."""
    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())

    # User A creates a confidential goal
    create_res = await mcp_client.call_tool(
        "create_goal",
        {
            "user_id": user_a_id,
            "title": "Confidential User A Goal",
            "objective": "Secret objective",
        },
    )
    goal_id = create_res["data"]["id"]

    # User B attempts to access User A's goal -> Must fail without exposing goal data
    user_b_res = await mcp_client.call_tool(
        "get_goal",
        {"goal_id": goal_id, "user_id": user_b_id},
    )
    assert user_b_res["isError"] is True
    assert "not found or access denied" in user_b_res["data"].lower()

    # User B attempts to pause User A's goal -> Must fail
    pause_attempt = await mcp_client.call_tool(
        "pause_goal",
        {"goal_id": goal_id, "user_id": user_b_id},
    )
    assert pause_attempt["isError"] is True
    assert "not found" in pause_attempt["data"].lower() or "denied" in pause_attempt["data"].lower()


@pytest.mark.asyncio
async def test_mcp_create_goal_validation_failure(mcp_client: MCPClient) -> None:
    """Requirement: Structured errors when invalid arguments are supplied."""
    user_id = str(uuid.uuid4())

    # Invalid title (< 3 characters)
    with pytest.raises(MCPClientError) as exc_info:
        await mcp_client.call_tool(
            "create_goal",
            {
                "user_id": user_id,
                "title": "ab",  # Too short
                "objective": "Valid objective text",
            },
        )
    assert exc_info.value.code == JSONRPCErrorCode.INVALID_PARAMS.value
    assert "validation" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_mcp_invalid_state_transition_handled_gracefully(
    mcp_client: MCPClient,
) -> None:
    """Requirement: Tool-level error handling for invalid state transitions."""
    user_id = str(uuid.uuid4())

    create_res = await mcp_client.call_tool(
        "create_goal",
        {
            "user_id": user_id,
            "title": "State Test Goal",
            "objective": "Testing illegal state transitions",
        },
    )
    goal_id = create_res["data"]["id"]

    # 1. Pause active goal -> OK
    pause_res = await mcp_client.call_tool(
        "pause_goal",
        {"goal_id": goal_id, "user_id": user_id},
    )
    assert pause_res["isError"] is False

    # 2. Pausing an already paused goal -> Tool execution error
    pause_again = await mcp_client.call_tool(
        "pause_goal",
        {"goal_id": goal_id, "user_id": user_id},
    )
    assert pause_again["isError"] is True
    assert "already paused" in pause_again["data"].lower()
