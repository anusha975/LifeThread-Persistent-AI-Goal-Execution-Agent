import uuid
from collections.abc import AsyncGenerator
from typing import Any

import app.db.session as db_session_module
import httpx
import pytest
from app.db.base import Base
from app.db.models.memory import MemoryType
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
# TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_memory_tools_discovery(mcp_client: MCPClient) -> None:
    """Verify all 5 Memory MCP tools are discoverable via MCP."""
    tools = await mcp_client.discover_tools()
    tool_names = [t["name"] for t in tools]

    expected = [
        "store_memory",
        "retrieve_memory",
        "search_memory",
        "update_memory",
        "delete_memory",
    ]
    for exp in expected:
        assert exp in tool_names, f"Tool {exp} should be registered and discovered"

    # Verify store_memory schema specifies input properties
    store_tool = next(t for t in tools if t["name"] == "store_memory")
    props = store_tool["inputSchema"]["properties"]
    assert "user_id" in props
    assert "content" in props
    assert "memory_type" in props
    assert "importance_score" in props
    assert "source" in props
    assert "metadata" in props


@pytest.mark.asyncio
async def test_store_and_retrieve_memory_all_types(mcp_client: MCPClient) -> None:
    """Verify storing and retrieving memories across all supported memory types."""
    user_id = str(uuid.uuid4())

    types_to_test = [
        (MemoryType.EPISODIC, "User completed mock interview with score 92%", 0.8),
        (MemoryType.SEMANTIC, "Transformer self-attention mechanism complexity is O(N^2)", 0.6),
        (MemoryType.GOAL, "Target: Finish system design preparation by next Friday", 0.9),
        (MemoryType.PREFERENCE, "User prefers study sessions early morning in 45-min blocks", 0.7),
    ]

    stored_ids = []
    for mtype, content, score in types_to_test:
        store_res = await mcp_client.call_tool(
            "store_memory",
            {
                "user_id": user_id,
                "content": content,
                "memory_type": mtype.value,
                "importance_score": score,
                "source": "unit_test",
                "metadata": {"test_run": True, "category": mtype.value.lower()},
            },
        )
        assert store_res["isError"] is False
        mem = store_res["data"]
        assert mem["user_id"] == user_id
        assert mem["content"] == content
        assert mem["memory_type"] == mtype.value
        assert mem["importance_score"] == score
        assert mem["source"] == "unit_test"
        assert mem["metadata"]["test_run"] is True
        assert "created_at" in mem
        assert "updated_at" in mem
        stored_ids.append((mem["id"], mtype, content, score))

    # Retrieve each memory
    for mem_id, mtype, content, score in stored_ids:
        get_res = await mcp_client.call_tool(
            "retrieve_memory",
            {"memory_id": mem_id, "user_id": user_id},
        )
        assert get_res["isError"] is False
        retrieved = get_res["data"]
        assert retrieved["id"] == mem_id
        assert retrieved["memory_type"] == mtype.value
        assert retrieved["content"] == content
        assert retrieved["importance_score"] == score


@pytest.mark.asyncio
async def test_search_memory_relational_filters(mcp_client: MCPClient) -> None:
    """Verify relational search filtering by query substring, memory_type, and min_importance."""
    user_id = str(uuid.uuid4())

    # Seed varied memories
    memories_data = [
        ("Python asynchronous programming with asyncio", MemoryType.SEMANTIC, 0.9, "docs"),
        ("Python GIL multi-threading limitations", MemoryType.SEMANTIC, 0.4, "docs"),
        ("User prefers dark mode and concise responses", MemoryType.PREFERENCE, 0.7, "ui"),
        ("System design mock interview went well", MemoryType.EPISODIC, 0.8, "interview"),
    ]

    for content, mtype, score, source in memories_data:
        await mcp_client.call_tool(
            "store_memory",
            {
                "user_id": user_id,
                "content": content,
                "memory_type": mtype.value,
                "importance_score": score,
                "source": source,
            },
        )

    # 1. Search by text query
    search_q = await mcp_client.call_tool(
        "search_memory",
        {"user_id": user_id, "query": "python"},
    )
    assert search_q["isError"] is False
    assert search_q["data"]["total"] == 2
    for item in search_q["data"]["items"]:
        assert "python" in item["content"].lower()

    # 2. Search by memory_type
    search_type = await mcp_client.call_tool(
        "search_memory",
        {"user_id": user_id, "memory_type": "PREFERENCE"},
    )
    assert search_type["isError"] is False
    assert search_type["data"]["total"] == 1
    assert search_type["data"]["items"][0]["memory_type"] == "PREFERENCE"

    # 3. Search with min_importance filter (>= 0.75)
    search_imp = await mcp_client.call_tool(
        "search_memory",
        {"user_id": user_id, "min_importance": 0.75},
    )
    assert search_imp["isError"] is False
    assert search_imp["data"]["total"] == 2
    for item in search_imp["data"]["items"]:
        assert item["importance_score"] >= 0.75

    # 4. Search with pagination (limit=1, offset=1)
    search_page = await mcp_client.call_tool(
        "search_memory",
        {"user_id": user_id, "limit": 1, "offset": 1},
    )
    assert search_page["isError"] is False
    assert search_page["data"]["total"] == 4
    assert len(search_page["data"]["items"]) == 1


@pytest.mark.asyncio
async def test_update_memory(mcp_client: MCPClient) -> None:
    """Verify updating memory content, importance score, and metadata."""
    user_id = str(uuid.uuid4())

    store_res = await mcp_client.call_tool(
        "store_memory",
        {
            "user_id": user_id,
            "content": "Initial memory content before refinement",
            "memory_type": "EPISODIC",
            "importance_score": 0.3,
            "metadata": {"version": 1},
        },
    )
    mem_id = store_res["data"]["id"]

    # Update
    update_res = await mcp_client.call_tool(
        "update_memory",
        {
            "memory_id": mem_id,
            "user_id": user_id,
            "content": "Updated refined memory content with higher impact",
            "importance_score": 0.85,
            "memory_type": "SEMANTIC",
            "metadata": {"version": 2, "verified": True},
        },
    )
    assert update_res["isError"] is False
    updated = update_res["data"]
    assert updated["id"] == mem_id
    assert updated["content"] == "Updated refined memory content with higher impact"
    assert updated["importance_score"] == 0.85
    assert updated["memory_type"] == "SEMANTIC"
    assert updated["metadata"]["version"] == 2
    assert updated["metadata"]["verified"] is True

    # Confirm retrieval reflects update
    get_res = await mcp_client.call_tool(
        "retrieve_memory",
        {"memory_id": mem_id, "user_id": user_id},
    )
    assert get_res["isError"] is False
    assert get_res["data"]["content"] == "Updated refined memory content with higher impact"


@pytest.mark.asyncio
async def test_delete_memory(mcp_client: MCPClient) -> None:
    """Verify deleting a memory permanently removes it and retrieval returns 404."""
    user_id = str(uuid.uuid4())

    store_res = await mcp_client.call_tool(
        "store_memory",
        {
            "user_id": user_id,
            "content": "Ephemeral scratchpad note to be deleted",
        },
    )
    mem_id = store_res["data"]["id"]

    # Delete
    del_res = await mcp_client.call_tool(
        "delete_memory",
        {"memory_id": mem_id, "user_id": user_id},
    )
    assert del_res["isError"] is False
    assert del_res["data"]["success"] is True
    assert del_res["data"]["memory_id"] == mem_id

    # Retrieve should return error
    get_res = await mcp_client.call_tool(
        "retrieve_memory",
        {"memory_id": mem_id, "user_id": user_id},
    )
    assert get_res["isError"] is True
    assert "not found" in str(get_res["data"]).lower()


@pytest.mark.asyncio
async def test_memory_multi_tenant_isolation(mcp_client: MCPClient) -> None:
    """Requirement 1: Strict user isolation across all memory tools."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    store_res = await mcp_client.call_tool(
        "store_memory",
        {
            "user_id": user_a,
            "content": "Confidential plan details for User A",
            "memory_type": "GOAL",
            "importance_score": 0.95,
        },
    )
    mem_id = store_res["data"]["id"]

    # User B cannot retrieve User A's memory
    b_get = await mcp_client.call_tool(
        "retrieve_memory",
        {"memory_id": mem_id, "user_id": user_b},
    )
    assert b_get["isError"] is True
    assert "not found" in str(b_get["data"]).lower()

    # User B cannot update User A's memory
    b_update = await mcp_client.call_tool(
        "update_memory",
        {"memory_id": mem_id, "user_id": user_b, "content": "Malicious override"},
    )
    assert b_update["isError"] is True
    assert "not found" in str(b_update["data"]).lower()

    # User B cannot delete User A's memory
    b_del = await mcp_client.call_tool(
        "delete_memory",
        {"memory_id": mem_id, "user_id": user_b},
    )
    assert b_del["isError"] is True
    assert "not found" in str(b_del["data"]).lower()

    # User B searching sees nothing from User A
    b_search = await mcp_client.call_tool(
        "search_memory",
        {"user_id": user_b, "query": "Confidential"},
    )
    assert b_search["isError"] is False
    assert b_search["data"]["total"] == 0
    assert len(b_search["data"]["items"]) == 0


@pytest.mark.asyncio
async def test_memory_tool_validation_errors(mcp_client: MCPClient) -> None:
    """Requirement 8: Tool-level validation enforces valid inputs."""
    user_id = str(uuid.uuid4())

    # 1. Empty content rejected
    with pytest.raises(MCPClientError) as exc_info:
        await mcp_client.call_tool(
            "store_memory",
            {
                "user_id": user_id,
                "content": "   ",
            },
        )
    assert exc_info.value.code == JSONRPCErrorCode.INVALID_PARAMS

    # 2. Importance score > 1.0 rejected
    with pytest.raises(MCPClientError) as exc_info2:
        await mcp_client.call_tool(
            "store_memory",
            {
                "user_id": user_id,
                "content": "Valid content",
                "importance_score": 1.5,
            },
        )
    assert exc_info2.value.code == JSONRPCErrorCode.INVALID_PARAMS

    # 3. Invalid memory type rejected
    with pytest.raises(MCPClientError) as exc_info3:
        await mcp_client.call_tool(
            "store_memory",
            {
                "user_id": user_id,
                "content": "Valid content",
                "memory_type": "NON_EXISTENT_TYPE",
            },
        )
    assert exc_info3.value.code == JSONRPCErrorCode.INVALID_PARAMS
