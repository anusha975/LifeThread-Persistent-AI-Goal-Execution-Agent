from datetime import UTC, datetime, timedelta

import pytest
from app.core.token_store import TokenDenylist
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def clean_token_denylist() -> None:
    TokenDenylist.clear()
    yield
    TokenDenylist.clear()


@pytest.fixture
async def async_test_client():
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_application()

    async def override_get_db():
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    await test_engine.dispose()


@pytest.fixture
async def auth_headers_user_a(async_test_client: AsyncClient) -> dict[str, str]:
    await async_test_client.post(
        "/api/v1/auth/register",
        json={"email": "alice@lifethread.ai", "password": "Password123"},
    )
    login_resp = await async_test_client.post(
        "/api/v1/auth/login",
        json={"email": "alice@lifethread.ai", "password": "Password123"},
    )
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def auth_headers_user_b(async_test_client: AsyncClient) -> dict[str, str]:
    await async_test_client.post(
        "/api/v1/auth/register",
        json={"email": "bob@lifethread.ai", "password": "Password123"},
    )
    login_resp = await async_test_client.post(
        "/api/v1/auth/login",
        json={"email": "bob@lifethread.ai", "password": "Password123"},
    )
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_goal_with_constraints_and_milestones(
    async_test_client: AsyncClient,
    auth_headers_user_a: dict[str, str],
) -> None:
    future_deadline = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    payload = {
        "title": "Launch Autonomous Marketing Campaign",
        "objective": "Design, deploy, and evaluate an automated multi-channel campaign.",
        "description": "High-priority strategic quarterly initiative.",
        "priority": "HIGH",
        "deadline": future_deadline,
        "success_criteria": ["Generate 500 qualified leads", "CAC under $50"],
        "constraints": [
            {
                "type": "budget",
                "value": "$5000 maximum spend",
                "metadata": {"currency": "USD", "cap": 5000},
            }
        ],
        "milestones": [
            {
                "title": "Audience Definition & Copy Creation",
                "description": "Finalize target personas and creative copy.",
                "order_index": 1,
            },
            {
                "title": "A/B Testing & Evaluation",
                "order_index": 2,
            },
        ],
    }

    response = await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json=payload,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Launch Autonomous Marketing Campaign"
    assert data["status"] == "ACTIVE"
    assert data["priority"] == "HIGH"
    assert len(data["success_criteria"]) == 2
    assert len(data["constraints"]) == 1
    assert data["constraints"][0]["type"] == "budget"
    assert data["constraints"][0]["metadata"]["cap"] == 5000
    assert len(data["milestones"]) == 2
    assert data["milestones"][0]["title"] == "Audience Definition & Copy Creation"


@pytest.mark.asyncio
async def test_goal_list_and_user_isolation(
    async_test_client: AsyncClient,
    auth_headers_user_a: dict[str, str],
    auth_headers_user_b: dict[str, str],
) -> None:
    # User A creates 2 goals
    await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json={"title": "Goal A1", "objective": "Objective for Goal A1"},
    )
    await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json={"title": "Goal A2", "objective": "Objective for Goal A2"},
    )

    # User B creates 1 goal
    await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_b,
        json={"title": "Goal B1", "objective": "Objective for Goal B1"},
    )

    # User A lists goals: expects 2
    resp_a = await async_test_client.get("/api/v1/goals", headers=auth_headers_user_a)
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert data_a["total"] == 2
    assert len(data_a["items"]) == 2
    assert all("Goal A" in item["title"] for item in data_a["items"])

    # User B lists goals: expects 1
    resp_b = await async_test_client.get("/api/v1/goals", headers=auth_headers_user_b)
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert data_b["total"] == 1
    assert len(data_b["items"]) == 1
    assert data_b["items"][0]["title"] == "Goal B1"


@pytest.mark.asyncio
async def test_get_goal_cross_user_forbidden(
    async_test_client: AsyncClient,
    auth_headers_user_a: dict[str, str],
    auth_headers_user_b: dict[str, str],
) -> None:
    # User A creates a goal
    create_resp = await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json={"title": "Secret Goal", "objective": "Classified objective information"},
    )
    goal_id = create_resp.json()["id"]

    # User A can retrieve it
    resp_a = await async_test_client.get(f"/api/v1/goals/{goal_id}", headers=auth_headers_user_a)
    assert resp_a.status_code == 200
    assert resp_a.json()["id"] == goal_id

    # User B attempts to access User A's goal -> Returns 404 Not Found
    resp_b = await async_test_client.get(f"/api/v1/goals/{goal_id}", headers=auth_headers_user_b)
    assert resp_b.status_code == 404
    assert "not found" in resp_b.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_update_goal_and_security(
    async_test_client: AsyncClient,
    auth_headers_user_a: dict[str, str],
    auth_headers_user_b: dict[str, str],
) -> None:
    create_resp = await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json={"title": "Original Title", "objective": "Original Objective description"},
    )
    goal_id = create_resp.json()["id"]

    # User B attempts update -> 404
    patch_b = await async_test_client.patch(
        f"/api/v1/goals/{goal_id}",
        headers=auth_headers_user_b,
        json={"title": "Hacked Title"},
    )
    assert patch_b.status_code == 404

    # User A updates
    patch_a = await async_test_client.patch(
        f"/api/v1/goals/{goal_id}",
        headers=auth_headers_user_a,
        json={"title": "Updated Title", "priority": "CRITICAL"},
    )
    assert patch_a.status_code == 200
    assert patch_a.json()["title"] == "Updated Title"
    assert patch_a.json()["priority"] == "CRITICAL"


@pytest.mark.asyncio
async def test_pause_and_resume_goal_lifecycle(
    async_test_client: AsyncClient,
    auth_headers_user_a: dict[str, str],
) -> None:
    create_resp = await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json={"title": "Pausable Goal", "objective": "Testing pause and resume states"},
    )
    goal_id = create_resp.json()["id"]

    # 1. Pause active goal -> 200 PAUSED
    pause_resp = await async_test_client.post(
        f"/api/v1/goals/{goal_id}/pause",
        headers=auth_headers_user_a,
    )
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "PAUSED"

    # 2. Pausing an already paused goal -> 400 Bad Request
    pause_again = await async_test_client.post(
        f"/api/v1/goals/{goal_id}/pause",
        headers=auth_headers_user_a,
    )
    assert pause_again.status_code == 400
    assert "already paused" in pause_again.json()["error"]["message"].lower()

    # 3. Resume paused goal -> 200 ACTIVE
    resume_resp = await async_test_client.post(
        f"/api/v1/goals/{goal_id}/resume",
        headers=auth_headers_user_a,
    )
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "ACTIVE"

    # 4. Resuming an already active goal -> 400 Bad Request
    resume_again = await async_test_client.post(
        f"/api/v1/goals/{goal_id}/resume",
        headers=auth_headers_user_a,
    )
    assert resume_again.status_code == 400
    assert "already active" in resume_again.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_complete_goal(
    async_test_client: AsyncClient,
    auth_headers_user_a: dict[str, str],
) -> None:
    create_resp = await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json={"title": "Completable Goal", "objective": "Testing completion lifecycle"},
    )
    goal_id = create_resp.json()["id"]

    complete_resp = await async_test_client.post(
        f"/api/v1/goals/{goal_id}/complete",
        headers=auth_headers_user_a,
    )
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "COMPLETED"

    # Cannot complete an already completed goal
    complete_again = await async_test_client.post(
        f"/api/v1/goals/{goal_id}/complete",
        headers=auth_headers_user_a,
    )
    assert complete_again.status_code == 400

    # Cannot pause a completed goal
    pause_completed = await async_test_client.post(
        f"/api/v1/goals/{goal_id}/pause",
        headers=auth_headers_user_a,
    )
    assert pause_completed.status_code == 400


@pytest.mark.asyncio
async def test_delete_goal_security_and_cascade(
    async_test_client: AsyncClient,
    auth_headers_user_a: dict[str, str],
    auth_headers_user_b: dict[str, str],
) -> None:
    create_resp = await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json={
            "title": "Disposable Goal",
            "objective": "Testing deletion mechanics",
            "constraints": [{"type": "scope", "value": "limited"}],
            "milestones": [{"title": "Phase 1"}],
        },
    )
    goal_id = create_resp.json()["id"]

    # User B cannot delete User A's goal -> 404
    del_b = await async_test_client.delete(f"/api/v1/goals/{goal_id}", headers=auth_headers_user_b)
    assert del_b.status_code == 404

    # User A deletes goal -> 204
    del_a = await async_test_client.delete(f"/api/v1/goals/{goal_id}", headers=auth_headers_user_a)
    assert del_a.status_code == 204

    # Verification: GET returns 404
    get_resp = await async_test_client.get(f"/api/v1/goals/{goal_id}", headers=auth_headers_user_a)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_validation_meaningful_title_and_deadline(
    async_test_client: AsyncClient,
    auth_headers_user_a: dict[str, str],
) -> None:
    # 1. Title with whitespace only
    resp_empty_title = await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json={"title": "   ", "objective": "Valid objective text here"},
    )
    assert resp_empty_title.status_code == 422

    # 2. Title too short (< 3 chars)
    resp_short_title = await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json={"title": "ab", "objective": "Valid objective text here"},
    )
    assert resp_short_title.status_code == 422

    # 3. Deadline in past
    past_deadline = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    resp_past_deadline = await async_test_client.post(
        "/api/v1/goals",
        headers=auth_headers_user_a,
        json={
            "title": "Past Deadline Goal",
            "objective": "Valid objective description text",
            "deadline": past_deadline,
        },
    )
    assert resp_past_deadline.status_code == 422
