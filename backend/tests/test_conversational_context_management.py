import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal, GoalMilestone, GoalPriority, GoalStatus, MilestoneStatus
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.services.orchestrator.date_parser import DateParser
from app.services.orchestrator.models import (
    AgentIntent,
)
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
async def test_date_parser_weekdays_and_relative():
    """Verify natural relative date parsing for conversational commands."""
    base = datetime(2026, 9, 21, 10, 0, 0, tzinfo=UTC)  # Monday Sep 21, 2026

    # Friday of this week -> Sep 25, 2026 at 18:00 UTC
    fri = DateParser.parse_deadline("Friday", base_time=base)
    assert fri is not None
    assert fri.year == 2026
    assert fri.month == 9
    assert fri.day == 25
    assert fri.hour == 18
    assert fri.minute == 0

    # Tomorrow -> Sep 22, 2026
    tom = DateParser.parse_deadline("tomorrow", base_time=base)
    assert tom is not None
    assert tom.day == 22

    # In 3 days -> Sep 24, 2026
    in_3 = DateParser.parse_deadline("in 3 days", base_time=base)
    assert in_3 is not None
    assert in_3.day == 24

    # ISO date
    iso = DateParser.parse_deadline("2026-10-15", base_time=base)
    assert iso is not None
    assert iso.month == 10
    assert iso.day == 15


@pytest.mark.asyncio
async def test_contextual_command_operates_on_active_goal_without_repeating_name(
    async_db: AsyncSession, client: AsyncClient
):
    """ACCEPTANCE CRITERIA:

    Contextual commands ('Change the deadline to Friday.') operate on the correct
    goal without requiring the user to repeat the full goal every time.
    """
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="context_user@example.com",
        display_name="Context Test User",
        password_hash="pw",
        is_active=True,
    )
    async_db.add(user)

    # User has 1 active goal
    goal = Goal(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Master Rust Concurrency",
        objective="Complete high performance async book",
        description="Systems engineering study",
        priority=GoalPriority.MEDIUM,
        status=GoalStatus.ACTIVE,
        deadline=datetime.now(UTC) + timedelta(days=20),
    )
    async_db.add(goal)
    await async_db.commit()

    token, _, _ = create_access_token(subject=str(user_id))
    headers = {"Authorization": f"Bearer {token}"}

    # User issues contextual command without mentioning goal title
    resp = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"message": "Change the deadline to Friday."},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["intent"] == AgentIntent.CHANGE_DEADLINE
    assert data["active_goal_id"] == str(goal.id)
    assert data["active_goal_title"] == "Master Rust Concurrency"
    assert "Successfully updated the deadline for **Master Rust Concurrency**" in data["message"]["content"]
    assert data["card_type"] == "deadline_updated"

    # Verify goal in database actually updated
    await async_db.refresh(goal)
    assert goal.deadline is not None
    assert goal.deadline.weekday() == 4  # Friday


@pytest.mark.asyncio
async def test_ambiguity_detection_prompts_clarification_when_multiple_goals_unfocused(
    async_db: AsyncSession, client: AsyncClient
):
    """When user has multiple active goals and no active goal is established in session,

    system detects high ambiguity, does NOT guess, and returns a clarification question.
    """
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="ambiguous_user@example.com",
        display_name="Multi Goal User",
        password_hash="pw",
        is_active=True,
    )
    async_db.add(user)

    # 2 Active goals in DB
    g1 = Goal(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Learn Advanced Rust",
        objective="Learn Rust",
        description="Rust",
        priority=GoalPriority.HIGH,
        status=GoalStatus.ACTIVE,
        deadline=datetime.now(UTC) + timedelta(days=14),
    )
    g2 = Goal(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Launch SaaS MVP",
        objective="Launch MVP",
        description="SaaS",
        priority=GoalPriority.CRITICAL,
        status=GoalStatus.ACTIVE,
        deadline=datetime.now(UTC) + timedelta(days=30),
    )
    async_db.add_all([g1, g2])
    await async_db.commit()

    token, _, _ = create_access_token(subject=str(user_id))
    headers = {"Authorization": f"Bearer {token}"}

    # Turn 1: User says "Change the deadline to Friday." on a clean session
    resp1 = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"message": "Change the deadline to Friday."},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()

    # Ambiguity detected -> Clarification prompt returned
    assert data1["clarification_prompt"] is not None
    assert data1["clarification_prompt"]["clarification_type"] == "AMBIGUOUS_GOAL"
    assert "You have 2 active goals" in data1["clarification_prompt"]["prompt_message"]
    assert len(data1["clarification_prompt"]["options"]) == 2

    option_labels = [opt["label"] for opt in data1["clarification_prompt"]["options"]]
    assert "Learn Advanced Rust" in option_labels
    assert "Launch SaaS MVP" in option_labels

    session_id = data1["session_id"]

    # Turn 2: User answers clarification by typing the goal name or ordinal "1"
    resp2 = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"session_id": session_id, "message": "Launch SaaS MVP"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()

    # Ambiguity resolved! Deferred command executes on "Launch SaaS MVP"
    assert data2["active_goal_id"] == str(g2.id)
    assert data2["active_goal_title"] == "Launch SaaS MVP"
    assert "Successfully updated the deadline for **Launch SaaS MVP**" in data2["message"]["content"]

    # Turn 3: Context continuity without repetition: "Make it critical"
    resp3 = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"session_id": session_id, "message": "Make it critical"},
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["active_goal_id"] == str(g2.id)
    assert "Updated priority of goal **Launch SaaS MVP** to **CRITICAL**" in data3["message"]["content"]


@pytest.mark.asyncio
async def test_clarification_response_by_ordinal_number(async_db: AsyncSession, client: AsyncClient):
    """Test answering clarification with '#1' or '1'."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="ordinal_user@example.com",
        display_name="Ordinal User",
        password_hash="pw",
        is_active=True,
    )
    async_db.add(user)

    g1 = Goal(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Write Research Paper",
        objective="Write",
        description="Paper",
        priority=GoalPriority.MEDIUM,
        status=GoalStatus.ACTIVE,
    )
    g2 = Goal(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Prepare Pitch Deck",
        objective="Deck",
        description="Pitch",
        priority=GoalPriority.HIGH,
        status=GoalStatus.ACTIVE,
    )
    async_db.add_all([g1, g2])
    await async_db.commit()

    token, _, _ = create_access_token(subject=str(user_id))
    headers = {"Authorization": f"Bearer {token}"}

    # Turn 1: ambiguous request
    resp1 = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"message": "Change the deadline to Friday."},
    )
    data1 = resp1.json()
    session_id = data1["session_id"]
    first_opt_title = data1["clarification_prompt"]["options"][0]["label"]

    # Turn 2: reply with "1"
    resp2 = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"session_id": session_id, "message": "1"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["active_goal_title"] == first_opt_title
    assert f"Successfully updated the deadline for **{first_opt_title}**" in data2["message"]["content"]


@pytest.mark.asyncio
async def test_clarification_cancellation(async_db: AsyncSession, client: AsyncClient):
    """Test user cancelling a pending clarification prompt."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="cancel_user@example.com",
        display_name="Cancel User",
        password_hash="pw",
        is_active=True,
    )
    async_db.add(user)

    g1 = Goal(id=uuid.uuid4(), user_id=user_id, title="Goal A", objective="Goal A obj", description="desc", priority=GoalPriority.HIGH, status=GoalStatus.ACTIVE)
    g2 = Goal(id=uuid.uuid4(), user_id=user_id, title="Goal B", objective="Goal B obj", description="desc", priority=GoalPriority.HIGH, status=GoalStatus.ACTIVE)
    async_db.add_all([g1, g2])
    await async_db.commit()

    token, _, _ = create_access_token(subject=str(user_id))
    headers = {"Authorization": f"Bearer {token}"}

    # Trigger clarification
    resp1 = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"message": "Change the deadline to Friday."},
    )
    session_id = resp1.json()["session_id"]

    # Cancel
    resp2 = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"session_id": session_id, "message": "never mind"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert "cancelled that request" in data2["message"]["content"]

    # Check context summary has no pending clarification
    summary_resp = await client.get(
        f"/api/v1/agent/chat/context?session_id={session_id}",
        headers=headers,
    )
    assert summary_resp.status_code == 200
    assert summary_resp.json()["pending_clarification"] is None


@pytest.mark.asyncio
async def test_milestone_and_memory_context_resolution(async_db: AsyncSession, client: AsyncClient):
    """Verify milestone query and memory query update session context correctly."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="milestone_mem_user@example.com",
        display_name="Full Stack Dev",
        password_hash="pw",
        is_active=True,
    )
    async_db.add(user)

    goal = Goal(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Full Stack Project",
        objective="Full Stack Objective",
        description="Full Stack Project Description",
        priority=GoalPriority.HIGH,
        status=GoalStatus.ACTIVE,
    )
    async_db.add(goal)

    m1 = GoalMilestone(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Phase 1: Architecture Setup",
        description="Architecture",
        order_index=0,
        status=MilestoneStatus.IN_PROGRESS,
    )
    m2 = GoalMilestone(
        id=uuid.uuid4(),
        goal_id=goal.id,
        title="Phase 2: Database Schema",
        description="DB",
        order_index=1,
        status=MilestoneStatus.PENDING,
    )
    async_db.add_all([m1, m2])
    await async_db.commit()

    token, _, _ = create_access_token(subject=str(user_id))
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Milestone query
    m_resp = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"message": "What is the milestone?"},
    )
    assert m_resp.status_code == 200
    m_data = m_resp.json()
    assert m_data["intent"] == AgentIntent.MILESTONE_QUERY
    assert m_data["active_milestone_title"] == "Phase 1: Architecture Setup"
    assert "Phase 1: Architecture Setup" in m_data["message"]["content"]

    session_id = m_data["session_id"]

    # 2. Store memory
    mem_resp = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"session_id": session_id, "message": "Remember that I struggle with SQL joins."},
    )
    assert mem_resp.status_code == 200
    mem_data = mem_resp.json()
    assert mem_data["intent"] == AgentIntent.REMEMBER_FACT

    # 3. Memory query
    query_resp = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={"session_id": session_id, "message": "What do you remember?"},
    )
    assert query_resp.status_code == 200
    query_data = query_resp.json()
    assert query_data["intent"] == AgentIntent.MEMORY_QUERY
    assert "SQL joins" in query_data["message"]["content"]
    assert query_data["last_referenced_memory_id"] is not None


@pytest.mark.asyncio
async def test_tenant_isolation_in_context_resolution(async_db: AsyncSession, client: AsyncClient):
    """Verify context resolver enforces strict tenant isolation."""
    user1_id = uuid.uuid4()
    user2_id = uuid.uuid4()

    u1 = User(id=user1_id, email="u1@example.com", display_name="U1", password_hash="pw", is_active=True)
    u2 = User(id=user2_id, email="u2@example.com", display_name="U2", password_hash="pw", is_active=True)
    async_db.add_all([u1, u2])

    g2 = Goal(
        id=uuid.uuid4(),
        user_id=user2_id,
        title="Secret User 2 Goal",
        objective="Secret Goal Objective",
        description="Secret Goal Description",
        priority=GoalPriority.CRITICAL,
        status=GoalStatus.ACTIVE,
    )
    async_db.add(g2)
    await async_db.commit()

    token1, _, _ = create_access_token(subject=str(user1_id))
    headers1 = {"Authorization": f"Bearer {token1}"}

    # User 1 tries to change deadline of User 2's goal
    resp = await client.post(
        "/api/v1/agent/chat",
        headers=headers1,
        json={"message": "Change the deadline of Secret User 2 Goal to Friday."},
    )
    assert resp.status_code == 200
    data = resp.json()
    # User 1 has no goals, cannot resolve User 2's goal
    assert "don't have an active goal" in data["message"]["content"].lower()
