import json
from datetime import UTC, datetime, timedelta

import pytest
from app.core.token_store import TokenDenylist
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.llm import get_llm_provider_dep
from app.main import create_application
from app.services.llm.mock import MockLLMProvider
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture
async def app_client(mock_llm: MockLLMProvider):
    TokenDenylist.clear()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def override_get_llm():
        yield mock_llm

    app = create_application()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider_dep] = override_get_llm

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Register user A
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "lead@example.com",
                "password": "StrongPassword123!",
                "display_name": "Lead Architect",
            },
        )
        login_a = await client.post(
            "/api/v1/auth/login",
            json={"email": "lead@example.com", "password": "StrongPassword123!"},
        )
        token_a = login_a.json()["access_token"]

        # Register user B
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "other@example.com",
                "password": "StrongPassword123!",
                "display_name": "Other User",
            },
        )
        login_b = await client.post(
            "/api/v1/auth/login",
            json={"email": "other@example.com", "password": "StrongPassword123!"},
        )
        token_b = login_b.json()["access_token"]

        yield client, token_a, token_b, mock_llm

    await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_goal_success(app_client):
    """Test successful decomposition of a valid goal into milestones, tasks, and dependencies."""
    client, token_a, _, mock_llm = app_client
    client.headers = {"Authorization": f"Bearer {token_a}"}

    # 1. Create a goal
    deadline = (datetime.now(UTC) + timedelta(days=14)).isoformat()
    goal_resp = await client.post(
        "/api/v1/goals",
        json={
            "title": "Build AI Search Engine",
            "objective": "Build and deploy a semantic vector search engine",
            "description": "High-throughput semantic search pipeline with pgvector",
            "priority": "HIGH",
            "deadline": deadline,
            "success_criteria": ["Sub-50ms latency", "Recall >= 90%"],
        },
    )
    assert goal_resp.status_code == 201
    goal_id = goal_resp.json()["id"]

    # 2. Mock LLM decomposition response
    mock_decomp = {
        "milestones": [
            {
                "title": "Phase 1: Ingestion & Embeddings",
                "description": "Data pipeline",
                "order_index": 0,
            },
            {
                "title": "Phase 2: Indexing & Retrieval",
                "description": "Vector search",
                "order_index": 1,
            },
        ],
        "tasks": [
            {
                "temp_id": "T1",
                "milestone_index": 0,
                "title": "Design embedding pipeline",
                "description": "Select embedding model and chunking strategy",
                "priority": "HIGH",
                "estimated_minutes": 60,
            },
            {
                "temp_id": "T2",
                "milestone_index": 0,
                "title": "Ingest documentation dataset",
                "description": "Extract and embed docs",
                "priority": "MEDIUM",
                "estimated_minutes": 120,
            },
            {
                "temp_id": "T3",
                "milestone_index": 1,
                "title": "Benchmark search query latency",
                "description": "Run performance load tests",
                "priority": "HIGH",
                "estimated_minutes": 90,
            },
        ],
        "dependencies": [
            {"task_temp_id": "T2", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"},
            {"task_temp_id": "T3", "depends_on_temp_id": "T2", "dependency_type": "BLOCKS"},
        ],
    }
    mock_llm.set_response(json.dumps(mock_decomp))

    # 3. Call decompose endpoint
    resp = await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})
    assert resp.status_code == 200
    data = resp.json()

    assert data["goal_id"] == goal_id
    assert data["version"] == 1
    assert data["is_active"] is True
    assert data["has_cycles"] is False
    assert len(data["tasks"]) == 3
    assert len(data["milestones"]) == 2
    assert len(data["dependencies"]) == 2

    # Verify linear critical path: T1 -> T2 -> T3: 60 + 120 + 90 = 270 minutes
    assert data["critical_path_duration_minutes"] == 270
    assert len(data["critical_path_task_ids"]) == 3


@pytest.mark.asyncio
async def test_cycle_detection_rejects_circular_dependencies(app_client):
    """Test that cyclical dependencies (T1 -> T2 -> T1) are rejected with HTTP 422."""
    client, token_a, _, mock_llm = app_client
    client.headers = {"Authorization": f"Bearer {token_a}"}

    goal_resp = await client.post(
        "/api/v1/goals",
        json={
            "title": "Cyclic Test Goal",
            "objective": "Test cycle rejection logic",
        },
    )
    goal_id = goal_resp.json()["id"]

    # Mock cyclical LLM output: T1 depends on T2 AND T2 depends on T1
    mock_cyclical = {
        "milestones": [{"title": "Phase 1", "order_index": 0}],
        "tasks": [
            {"temp_id": "T1", "milestone_index": 0, "title": "Task One", "estimated_minutes": 30},
            {"temp_id": "T2", "milestone_index": 0, "title": "Task Two", "estimated_minutes": 30},
        ],
        "dependencies": [
            {"task_temp_id": "T2", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"},
            {"task_temp_id": "T1", "depends_on_temp_id": "T2", "dependency_type": "BLOCKS"},
        ],
    }
    mock_llm.set_response(json.dumps(mock_cyclical))

    resp = await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"]["code"] == "CIRCULAR_DEPENDENCY_DETECTED"
    assert "Circular dependency detected" in data["error"]["message"]


@pytest.mark.asyncio
async def test_critical_path_calculation(app_client):
    """Test Critical Path Method (CPM) identifying bottleneck path accurately."""
    client, token_a, _, mock_llm = app_client
    client.headers = {"Authorization": f"Bearer {token_a}"}

    goal_resp = await client.post(
        "/api/v1/goals",
        json={"title": "CPM Test Goal", "objective": "Verify Critical Path Calculation"},
    )
    goal_id = goal_resp.json()["id"]

    # Graph structure:
    # T1 (60m) is root
    # Path A: T1 -> T2 (120m) -> T4 (60m) = 240m (Longer -> Critical Path)
    # Path B: T1 -> T3 (30m)  -> T4 (60m) = 150m (Shorter -> Non-critical)
    mock_cpm = {
        "milestones": [{"title": "Sprint 1", "order_index": 0}],
        "tasks": [
            {"temp_id": "T1", "milestone_index": 0, "title": "Task 1", "estimated_minutes": 60},
            {
                "temp_id": "T2",
                "milestone_index": 0,
                "title": "Task 2 (Heavy)",
                "estimated_minutes": 120,
            },
            {
                "temp_id": "T3",
                "milestone_index": 0,
                "title": "Task 3 (Light)",
                "estimated_minutes": 30,
            },
            {
                "temp_id": "T4",
                "milestone_index": 0,
                "title": "Task 4 (Final)",
                "estimated_minutes": 60,
            },
        ],
        "dependencies": [
            {"task_temp_id": "T2", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"},
            {"task_temp_id": "T3", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"},
            {"task_temp_id": "T4", "depends_on_temp_id": "T2", "dependency_type": "BLOCKS"},
            {"task_temp_id": "T4", "depends_on_temp_id": "T3", "dependency_type": "BLOCKS"},
        ],
    }
    mock_llm.set_response(json.dumps(mock_cpm))

    resp = await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})
    assert resp.status_code == 200
    data = resp.json()

    assert data["critical_path_duration_minutes"] == 240  # 60 + 120 + 60
    assert len(data["critical_path_task_ids"]) == 3  # T1, T2, T4


@pytest.mark.asyncio
async def test_version_preservation_and_no_silent_overwrite(app_client):
    """Test Requirement 8 & 9: Preserves previous decomposition and requires confirmation to re-decompose."""
    client, token_a, _, mock_llm = app_client
    client.headers = {"Authorization": f"Bearer {token_a}"}

    goal_resp = await client.post(
        "/api/v1/goals",
        json={"title": "Versioning Goal", "objective": "Test revision history preservation"},
    )
    goal_id = goal_resp.json()["id"]

    v1_mock = {
        "milestones": [{"title": "v1 Milestone", "order_index": 0}],
        "tasks": [
            {"temp_id": "T1", "milestone_index": 0, "title": "v1 Task", "estimated_minutes": 45}
        ],
        "dependencies": [],
    }
    mock_llm.set_response(json.dumps(v1_mock))

    # Initial decomposition -> version 1
    resp1 = await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})
    assert resp1.status_code == 200
    assert resp1.json()["version"] == 1

    # Attempt re-decomposition without confirm_new_version -> Should fail with 409 Conflict
    v2_mock = {
        "milestones": [{"title": "v2 Milestone", "order_index": 0}],
        "tasks": [
            {"temp_id": "T1", "milestone_index": 0, "title": "v2 Task", "estimated_minutes": 90}
        ],
        "dependencies": [],
    }
    mock_llm.set_response(json.dumps(v2_mock))

    resp2_fail = await client.post(
        f"/api/v1/goals/{goal_id}/decompose", json={"confirm_new_version": False}
    )
    assert resp2_fail.status_code == 409
    assert resp2_fail.json()["error"]["code"] == "DECOMPOSITION_ALREADY_EXISTS"

    # Re-decompose with confirm_new_version = True -> Should succeed with version 2
    resp2_ok = await client.post(
        f"/api/v1/goals/{goal_id}/decompose", json={"confirm_new_version": True}
    )
    assert resp2_ok.status_code == 200
    assert resp2_ok.json()["version"] == 2

    # Verify version 1 tasks are PRESERVED and untouched
    tasks_v1 = await client.get(f"/api/v1/goals/{goal_id}/tasks?version=1")
    assert tasks_v1.status_code == 200
    assert tasks_v1.json()["version"] == 1
    assert tasks_v1.json()["items"][0]["title"] == "v1 Task"

    # Verify version 2 tasks are returned for version 2
    tasks_v2 = await client.get(f"/api/v1/goals/{goal_id}/tasks?version=2")
    assert tasks_v2.status_code == 200
    assert tasks_v2.json()["version"] == 2
    assert tasks_v2.json()["items"][0]["title"] == "v2 Task"


@pytest.mark.asyncio
async def test_get_dependencies_endpoint(app_client):
    """Test GET /api/v1/goals/{goal_id}/dependencies endpoint returning nodes, edges, and topological order."""
    client, token_a, _, mock_llm = app_client
    client.headers = {"Authorization": f"Bearer {token_a}"}

    goal_resp = await client.post(
        "/api/v1/goals",
        json={"title": "Graph Query Goal", "objective": "Query dependency DAG"},
    )
    goal_id = goal_resp.json()["id"]

    mock_decomp = {
        "milestones": [{"title": "Phase 1", "order_index": 0}],
        "tasks": [
            {"temp_id": "T1", "milestone_index": 0, "title": "A", "estimated_minutes": 10},
            {"temp_id": "T2", "milestone_index": 0, "title": "B", "estimated_minutes": 20},
        ],
        "dependencies": [
            {"task_temp_id": "T2", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"},
        ],
    }
    mock_llm.set_response(json.dumps(mock_decomp))
    await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})

    graph_resp = await client.get(f"/api/v1/goals/{goal_id}/dependencies")
    assert graph_resp.status_code == 200
    graph_data = graph_resp.json()

    assert graph_data["goal_id"] == goal_id
    assert graph_data["version"] == 1
    assert len(graph_data["nodes"]) == 2
    assert len(graph_data["edges"]) == 1
    assert len(graph_data["topological_order"]) == 2
    assert len(graph_data["critical_path"]) == 2


@pytest.mark.asyncio
async def test_cross_tenant_isolation_forbidden(app_client):
    """Test that users cannot decompose or view tasks of another user's goal."""
    client, token_a, token_b, _ = app_client

    # User A creates a goal
    client.headers = {"Authorization": f"Bearer {token_a}"}
    goal_resp = await client.post(
        "/api/v1/goals",
        json={"title": "Private Goal A", "objective": "Confidential mission"},
    )
    goal_id = goal_resp.json()["id"]

    # User B attempts to decompose User A's goal -> 404
    client.headers = {"Authorization": f"Bearer {token_b}"}
    decomp_resp = await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})
    assert decomp_resp.status_code == 404

    # User B attempts to get User A's tasks -> 404
    tasks_resp = await client.get(f"/api/v1/goals/{goal_id}/tasks")
    assert tasks_resp.status_code == 404

    # User B attempts to get User A's dependencies -> 404
    dep_resp = await client.get(f"/api/v1/goals/{goal_id}/dependencies")
    assert dep_resp.status_code == 404
