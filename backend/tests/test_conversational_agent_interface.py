import uuid

import pytest
import pytest_asyncio
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal
from app.db.models.memory import Memory
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(async_db: AsyncSession):
    async def override_get_db():
        yield async_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_conversational_agent_full_orchestration_flow(async_db: AsyncSession, client: AsyncClient):
    """Test Module 32: Conversational Agent Interface & Real Orchestrator execution.

    Validates all required conversational commands:
    1. 'Create a goal.'
    2. 'Create a goal: Learn Advanced Rust in 30 days'
    3. 'What should I do next?'
    4. 'I only have one hour today.'
    5. 'What changed?'
    6. 'Why did my plan change?'
    7. 'Remember that I struggle with SQL joins.'
    8. 'What is blocking my goal?'
    9. Session, user, active goal, and current task context maintenance.
    """
    # 1. Create authenticated user
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="orchestrator_user@example.com",
        display_name="Rust Engineer",
        password_hash="pw",
        is_active=True,
    )
    async_db.add(user)
    await async_db.commit()

    token, _, _ = create_access_token(subject=str(user_id))
    headers = {"Authorization": f"Bearer {token}"}

    # =========================================================================
    # Step 1: Prompt underspecified "Create a goal."
    # =========================================================================
    res = await client.post("/api/v1/agent/chat", json={"message": "Create a goal."}, headers=headers)
    assert res.status_code == 200
    data = res.json()
    session_id = data["session_id"]
    assert data["intent"] == "CREATE_GOAL"
    assert "What would you like to achieve" in data["message"]["content"]
    assert len(data["suggested_replies"]) > 0

    # =========================================================================
    # Step 2: "Create a goal: Learn Advanced Rust in 30 days"
    # =========================================================================
    res = await client.post(
        "/api/v1/agent/chat",
        json={"message": "Create a goal: Learn Advanced Rust in 30 days", "session_id": session_id},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "CREATE_GOAL"
    assert data["active_goal_id"] is not None
    assert "Learn Advanced Rust in 30 days" in data["active_goal_title"]
    assert data["card_type"] == "goal_created"
    assert data["card_data"]["tasks_count"] > 0
    goal_id = uuid.UUID(data["active_goal_id"])

    # Verify goal was really created in DB
    db_goal = await async_db.get(Goal, goal_id)
    assert db_goal is not None
    assert db_goal.title == "Learn Advanced Rust in 30 days"
    assert db_goal.user_id == user_id

    # =========================================================================
    # Step 3: "What should I do next?"
    # =========================================================================
    res = await client.post(
        "/api/v1/agent/chat",
        json={"message": "What should I do next?", "session_id": session_id},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "NEXT_ACTION"
    assert data["current_task_id"] is not None
    assert data["current_task_title"] is not None
    assert data["card_type"] == "next_action"
    assert data["card_data"]["task_id"] == data["current_task_id"]
    assert "critical path" in data["message"]["content"].lower()

    # =========================================================================
    # Step 4: "I only have one hour today." (Capacity constraint shift & replan)
    # =========================================================================
    res = await client.post(
        "/api/v1/agent/chat",
        json={"message": "I only have one hour today.", "session_id": session_id},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "CAPACITY_CONSTRAINT"
    assert "1.0 hour" in data["message"]["content"]
    assert "Plan v2" in data["message"]["content"]
    assert data["card_type"] == "capacity_replan"

    # =========================================================================
    # Step 5: "What changed?"
    # =========================================================================
    res = await client.post(
        "/api/v1/agent/chat",
        json={"message": "What changed?", "session_id": session_id},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "WHAT_CHANGED"
    assert data["card_type"] == "plan_diff"
    assert data["card_data"]["plan_changed"] is True
    assert "Plan v1" in data["message"]["content"]
    assert "Plan v2" in data["message"]["content"]

    # =========================================================================
    # Step 6: "Why did my plan change?"
    # =========================================================================
    res = await client.post(
        "/api/v1/agent/chat",
        json={"message": "Why did my plan change?", "session_id": session_id},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "WHY_PLAN_CHANGED"
    assert data["card_type"] == "replanning_why"
    assert "AVAILABLE_TIME_CHANGED" in data["message"]["content"]
    # Verify CoT is not exposed
    assert "thought:" not in data["message"]["content"].lower()
    assert "chain_of_thought" not in data["message"]["content"].lower()

    # =========================================================================
    # Step 7: "Remember that I struggle with SQL joins."
    # =========================================================================
    res = await client.post(
        "/api/v1/agent/chat",
        json={"message": "Remember that I struggle with SQL joins.", "session_id": session_id},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "REMEMBER_FACT"
    assert data["card_type"] == "memory_stored"
    assert data["card_data"]["category"] == "Learned weakness"

    # Verify memory was persisted to DB
    mem_id = uuid.UUID(data["card_data"]["memory_id"])
    db_mem = await async_db.get(Memory, mem_id)
    assert db_mem is not None
    assert "struggle with sql joins" in db_mem.content.lower()
    assert db_mem.user_id == user_id
    assert db_mem.metadata_json.get("category") == "Learned weakness"

    # =========================================================================
    # Step 8: "What is blocking my goal?"
    # =========================================================================
    res = await client.post(
        "/api/v1/agent/chat",
        json={"message": "What is blocking my goal?", "session_id": session_id},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "WHAT_IS_BLOCKING"
    assert data["card_type"] == "blockers_diagnostic"
    assert "Deadline Risk" in data["message"]["content"]

    # =========================================================================
    # Step 9: Get Conversation Context Summary
    # =========================================================================
    res = await client.get(f"/api/v1/agent/chat/context?session_id={session_id}", headers=headers)
    assert res.status_code == 200
    ctx = res.json()
    assert ctx["session_id"] == session_id
    assert ctx["active_goal_title"] == "Learn Advanced Rust in 30 days"
    assert ctx["current_task_id"] is not None
    assert ctx["active_goals_count"] >= 1
    assert ctx["total_memories_count"] >= 1
    assert ctx["learned_weaknesses_count"] >= 1
    assert len(ctx["recent_intents"]) >= 4

    # =========================================================================
    # Step 10: Multi-tenant Session Isolation
    # =========================================================================
    other_user_id = uuid.uuid4()
    other_user = User(
        id=other_user_id,
        email="attacker@example.com",
        display_name="Attacker",
        password_hash="pw",
        is_active=True,
    )
    async_db.add(other_user)
    await async_db.commit()

    other_token, _, _ = create_access_token(subject=str(other_user_id))
    other_headers = {"Authorization": f"Bearer {other_token}"}

    # Attacker tries to query original user's session
    bad_res = await client.get(f"/api/v1/agent/chat/sessions/{session_id}", headers=other_headers)
    # The session store must enforce isolation and return a fresh or isolated session for attacker
    # rather than leaking original user's messages
    bad_data = bad_res.json()
    assert bad_data["user_id"] == str(other_user_id)
    assert len(bad_data["messages"]) == 0
