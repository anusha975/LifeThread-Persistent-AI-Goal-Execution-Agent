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
        # User A
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "planner@example.com",
                "password": "StrongPassword123!",
                "display_name": "Planner Lead",
                "timezone": "UTC",
            },
        )
        login_a = await client.post(
            "/api/v1/auth/login",
            json={"email": "planner@example.com", "password": "StrongPassword123!"},
        )
        token_a = login_a.json()["access_token"]

        # User B
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
async def test_generate_plan_respects_dependencies(app_client):
    """Test Requirement 1: A task is NEVER scheduled before its prerequisite completes."""
    client, token_a, _, mock_llm = app_client
    client.headers = {"Authorization": f"Bearer {token_a}"}

    # 1. Create a goal with ample deadline
    deadline = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    goal_resp = await client.post(
        "/api/v1/goals",
        json={
            "title": "Machine Learning Pipeline",
            "objective": "Build automated ML training and evaluation pipeline",
            "deadline": deadline,
        },
    )
    goal_id = goal_resp.json()["id"]

    # 2. Decompose into T1 -> T2 -> T3 chain
    mock_llm.set_response(
        json.dumps(
            {
                "milestones": [{"title": "Phase 1", "order_index": 0}],
                "tasks": [
                    {
                        "temp_id": "T1",
                        "milestone_index": 0,
                        "title": "Data Preprocessing",
                        "estimated_minutes": 120,
                    },
                    {
                        "temp_id": "T2",
                        "milestone_index": 0,
                        "title": "Model Training",
                        "estimated_minutes": 180,
                    },
                    {
                        "temp_id": "T3",
                        "milestone_index": 0,
                        "title": "Model Evaluation",
                        "estimated_minutes": 60,
                    },
                ],
                "dependencies": [
                    {"task_temp_id": "T2", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"},
                    {"task_temp_id": "T3", "depends_on_temp_id": "T2", "dependency_type": "BLOCKS"},
                ],
            }
        )
    )
    await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})

    # 3. Generate Plan
    start_time = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)
    plan_resp = await client.post(
        f"/api/v1/goals/{goal_id}/plan",
        json={
            "daily_available_hours": 4.0,
            "start_date": start_time.isoformat(),
            "workdays_only": False,
        },
    )
    assert plan_resp.status_code == 200
    plan_data = plan_resp.json()

    assert plan_data["version"] == 1
    assert plan_data["status"] == "ACTIVE"
    assert plan_data["is_feasible"] is True
    assert plan_data["total_duration_minutes"] == 360  # 120 + 180 + 60
    assert len(plan_data["items"]) == 3

    # Map items by task title
    items_by_title = {item["task_title"]: item for item in plan_data["items"]}
    t1 = items_by_title["Data Preprocessing"]
    t2 = items_by_title["Model Training"]
    t3 = items_by_title["Model Evaluation"]

    # Verify dependency sequencing: T2 start >= T1 end, T3 start >= T2 end
    t1_end = datetime.fromisoformat(t1["scheduled_end"])
    t2_start = datetime.fromisoformat(t2["scheduled_start"])
    t2_end = datetime.fromisoformat(t2["scheduled_end"])
    t3_start = datetime.fromisoformat(t3["scheduled_start"])

    assert t2_start >= t1_end, "T2 must start after T1 finishes"
    assert t3_start >= t2_end, "T3 must start after T2 finishes"

    # Verify rationale explains decision
    assert (
        "prerequisite" in t2["rationale"].lower() or "data preprocessing" in t2["rationale"].lower()
    )


@pytest.mark.asyncio
async def test_detect_infeasible_plan_due_to_deadline(app_client):
    """Test Requirement 5: Detects when task durations exceed goal deadline, marking INFEASIBLE."""
    client, token_a, _, mock_llm = app_client
    client.headers = {"Authorization": f"Bearer {token_a}"}

    # Tight deadline: only 1 day away
    tight_deadline = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    goal_resp = await client.post(
        "/api/v1/goals",
        json={
            "title": "Impossible Sprint",
            "objective": "Complete massive project in 1 day",
            "deadline": tight_deadline,
        },
    )
    goal_id = goal_resp.json()["id"]

    # Tasks require 2400 minutes (40 hours) of work
    mock_llm.set_response(
        json.dumps(
            {
                "milestones": [{"title": "Heavy Phase", "order_index": 0}],
                "tasks": [
                    {
                        "temp_id": "T1",
                        "milestone_index": 0,
                        "title": "Heavy Task 1",
                        "estimated_minutes": 1200,
                    },
                    {
                        "temp_id": "T2",
                        "milestone_index": 0,
                        "title": "Heavy Task 2",
                        "estimated_minutes": 1200,
                    },
                ],
                "dependencies": [
                    {"task_temp_id": "T2", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"}
                ],
            }
        )
    )
    await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})

    # Plan with 4 hours/day availability -> requires 10 working days
    plan_resp = await client.post(
        f"/api/v1/goals/{goal_id}/plan",
        json={"daily_available_hours": 4.0},
    )
    assert plan_resp.status_code == 200
    plan_data = plan_resp.json()

    assert plan_data["is_feasible"] is False
    assert plan_data["status"] == "INFEASIBLE"
    assert plan_data["risk_level"] == "CRITICAL"
    assert plan_data["deadline_risk"] > 1.0
    assert "exceeds goal deadline" in plan_data["reason"].lower()


@pytest.mark.asyncio
async def test_plan_versioning_and_superseding(app_client):
    """Test Requirement 7 & 8: Support plan versioning and preserve old plans as SUPERSEDED."""
    client, token_a, _, mock_llm = app_client
    client.headers = {"Authorization": f"Bearer {token_a}"}

    deadline = (datetime.now(UTC) + timedelta(days=20)).isoformat()
    goal_resp = await client.post(
        "/api/v1/goals",
        json={
            "title": "Versioned Planning Goal",
            "objective": "Test multiple plan revisions",
            "deadline": deadline,
        },
    )
    goal_id = goal_resp.json()["id"]

    mock_llm.set_response(
        json.dumps(
            {
                "milestones": [{"title": "Phase 1", "order_index": 0}],
                "tasks": [
                    {
                        "temp_id": "T1",
                        "milestone_index": 0,
                        "title": "Initial Task",
                        "estimated_minutes": 60,
                    }
                ],
                "dependencies": [],
            }
        )
    )
    await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})

    # Plan version 1
    resp_v1 = await client.post(
        f"/api/v1/goals/{goal_id}/plan", json={"daily_available_hours": 2.0}
    )
    assert resp_v1.status_code == 200
    assert resp_v1.json()["version"] == 1
    assert resp_v1.json()["status"] == "ACTIVE"

    # Plan version 2 (e.g. replanned with more available hours)
    resp_v2 = await client.post(
        f"/api/v1/goals/{goal_id}/plan",
        json={"daily_available_hours": 6.0, "reason": "Increased daily capacity to 6h"},
    )
    assert resp_v2.status_code == 200
    assert resp_v2.json()["version"] == 2
    assert resp_v2.json()["status"] == "ACTIVE"

    # List plans endpoint: should contain 2 versions
    list_resp = await client.get(f"/api/v1/goals/{goal_id}/plans")
    assert list_resp.status_code == 200
    plans = list_resp.json()["items"]
    assert len(plans) == 2

    # Check version 1 is marked SUPERSEDED
    v1_summary = next(p for p in plans if p["version"] == 1)
    v2_summary = next(p for p in plans if p["version"] == 2)
    assert v1_summary["status"] == "SUPERSEDED"
    assert v2_summary["status"] == "ACTIVE"

    # Retrieve specific version 1
    get_v1 = await client.get(f"/api/v1/goals/{goal_id}/plans/1")
    assert get_v1.status_code == 200
    assert get_v1.json()["version"] == 1
    assert get_v1.json()["status"] == "SUPERSEDED"


@pytest.mark.asyncio
async def test_deadline_risk_and_schedule_utilization_metrics(app_client):
    """Test Requirement 9 & 10: Calculate deadline risk and schedule utilization."""
    client, token_a, _, mock_llm = app_client
    client.headers = {"Authorization": f"Bearer {token_a}"}

    # Comfortable 30-day deadline
    deadline = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    goal_resp = await client.post(
        "/api/v1/goals",
        json={
            "title": "Metrics Goal",
            "objective": "Check risk and utilization formulas",
            "deadline": deadline,
        },
    )
    goal_id = goal_resp.json()["id"]

    mock_llm.set_response(
        json.dumps(
            {
                "milestones": [{"title": "Phase 1", "order_index": 0}],
                "tasks": [
                    {
                        "temp_id": "T1",
                        "milestone_index": 0,
                        "title": "Task A",
                        "estimated_minutes": 120,
                    },
                    {
                        "temp_id": "T2",
                        "milestone_index": 0,
                        "title": "Task B",
                        "estimated_minutes": 120,
                    },
                ],
                "dependencies": [],
            }
        )
    )
    await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})

    plan_resp = await client.post(
        f"/api/v1/goals/{goal_id}/plan",
        json={"daily_available_hours": 4.0},
    )
    assert plan_resp.status_code == 200
    data = plan_resp.json()

    assert data["risk_level"] == "LOW"
    assert 0.0 <= data["deadline_risk"] < 0.65
    assert data["schedule_utilization"] > 0.0


@pytest.mark.asyncio
async def test_planning_cross_tenant_isolation(app_client):
    """Test that User B cannot plan or inspect plans of User A's goal."""
    client, token_a, token_b, mock_llm = app_client

    client.headers = {"Authorization": f"Bearer {token_a}"}
    goal_resp = await client.post(
        "/api/v1/goals",
        json={"title": "User A Private Goal", "objective": "Classified"},
    )
    goal_id = goal_resp.json()["id"]

    mock_llm.set_response(
        json.dumps(
            {
                "milestones": [{"title": "P1", "order_index": 0}],
                "tasks": [
                    {
                        "temp_id": "T1",
                        "milestone_index": 0,
                        "title": "Task 1",
                        "estimated_minutes": 60,
                    }
                ],
                "dependencies": [],
            }
        )
    )
    await client.post(f"/api/v1/goals/{goal_id}/decompose", json={})
    await client.post(f"/api/v1/goals/{goal_id}/plan", json={})

    # User B attempts to access User A's plan
    client.headers = {"Authorization": f"Bearer {token_b}"}
    assert (await client.post(f"/api/v1/goals/{goal_id}/plan", json={})).status_code == 404
    assert (await client.get(f"/api/v1/goals/{goal_id}/plan")).status_code == 404
    assert (await client.get(f"/api/v1/goals/{goal_id}/plans")).status_code == 404
    assert (await client.get(f"/api/v1/goals/{goal_id}/plans/1")).status_code == 404
