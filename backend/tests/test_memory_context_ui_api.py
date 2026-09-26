import uuid

import pytest
import pytest_asyncio
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.memory import Memory, MemoryType
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
async def test_memory_context_api_full_suite(async_db: AsyncSession, client: AsyncClient):
    """Test full Module 30 suite:

    - Categories: Goal memory, Preference, Past outcome, Learned weakness, Relevant knowledge
    - Fields: memory, source, confidence, related goal, created date
    - User operations: correct memory, delete memory, inspect source
    - Strict tenant isolation
    """
    # 1. Create two test users
    user_a = User(
        id=uuid.uuid4(),
        email="memory_user_a@example.com",
        password_hash="pw",
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        email="memory_user_b@example.com",
        password_hash="pw",
        is_active=True,
    )
    async_db.add_all([user_a, user_b])
    await async_db.commit()

    # 2. Create a goal for User A
    goal = Goal(
        id=uuid.uuid4(),
        user_id=user_a.id,
        title="Pass Distributed Systems Exam",
        objective="Master Raft consensus and vector clocks",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.HIGH,
    )
    async_db.add(goal)
    await async_db.commit()

    # 3. Create persistent memories representing each of the 5 canonical categories
    mem_goal = Memory(
        id=uuid.uuid4(),
        user_id=user_a.id,
        memory_type=MemoryType.GOAL,
        content="Must maintain minimum 8 hours weekly study schedule for distributed systems",
        confidence=0.95,
        importance_score=0.85,
        source="goal_decomposition",
        metadata_json={
            "goal_id": str(goal.id),
            "goal_title": goal.title,
            "category": "Goal memory",
        },
    )

    mem_pref = Memory(
        id=uuid.uuid4(),
        user_id=user_a.id,
        memory_type=MemoryType.PREFERENCE,
        content="Prefers studying in focused 25-minute Pomodoro sessions with zero notifications",
        confidence=1.0,
        importance_score=0.75,
        source="user_preference",
        metadata_json={
            "category": "Preference",
            "learning_type": "PREFERENCE",
        },
    )

    mem_outcome = Memory(
        id=uuid.uuid4(),
        user_id=user_a.id,
        memory_type=MemoryType.EPISODIC,
        content="Completed Raft leader election lab with 100% test passing in 42 minutes",
        confidence=0.98,
        importance_score=0.8,
        source="agent_execution",
        metadata_json={
            "goal_id": str(goal.id),
            "task_title": "Implement Raft Leader Election",
            "outcome_id": "out-12345",
            "source_action": "LAB_EXECUTION",
            "category": "Past outcome",
        },
    )

    mem_weakness = Memory(
        id=uuid.uuid4(),
        user_id=user_a.id,
        memory_type=MemoryType.SEMANTIC,
        content="Struggles with log compaction and snapshotting corner cases under network partition",
        confidence=0.88,
        importance_score=0.9,
        source="agent_learning_loop",
        metadata_json={
            "goal_id": str(goal.id),
            "learning_type": "WEAKNESS",
            "domain": "Distributed Systems",
            "topic": "Log Compaction",
            "epistemic_qualifier": "Provisional hypothesis",
            "is_hypothesis": True,
            "is_factual": False,
            "category": "Learned weakness",
        },
    )

    mem_knowledge = Memory(
        id=uuid.uuid4(),
        user_id=user_a.id,
        memory_type=MemoryType.SEMANTIC,
        content="Vector clocks provide causal order guarantees without synchronized physical wall clocks",
        confidence=1.0,
        importance_score=0.7,
        source="doc_chunk:raft_paper.pdf",
        metadata_json={
            "category": "Relevant knowledge",
            "domain": "Distributed Systems",
        },
    )

    # Memory for User B to test tenant isolation
    mem_user_b = Memory(
        id=uuid.uuid4(),
        user_id=user_b.id,
        memory_type=MemoryType.PREFERENCE,
        content="User B private secret preference",
        confidence=1.0,
        importance_score=0.5,
        source="user",
        metadata_json={},
    )

    async_db.add_all([mem_goal, mem_pref, mem_outcome, mem_weakness, mem_knowledge, mem_user_b])
    await async_db.commit()

    token_a, _, _ = create_access_token(subject=str(user_a.id))
    headers_a = {"Authorization": f"Bearer {token_a}"}

    token_b, _, _ = create_access_token(subject=str(user_b.id))
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 4. List memories for User A (Check all 5 categories & counts)
    res = await client.get("/api/v1/memories", headers=headers_a)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    assert len(data["items"]) == 5
    assert data["category_counts"]["Goal memory"] == 1
    assert data["category_counts"]["Preference"] == 1
    assert data["category_counts"]["Past outcome"] == 1
    assert data["category_counts"]["Learned weakness"] == 1
    assert data["category_counts"]["Relevant knowledge"] == 1

    # 5. Check item fields for memory, source, confidence, related goal, created date
    goal_mem_item = next(item for item in data["items"] if item["id"] == str(mem_goal.id))
    assert goal_mem_item["memory"] == mem_goal.content
    assert goal_mem_item["source"] == "goal_decomposition"
    assert goal_mem_item["confidence"] == 0.95
    assert goal_mem_item["related_goal"] is not None
    assert goal_mem_item["related_goal"]["id"] == str(goal.id)
    assert goal_mem_item["related_goal"]["title"] == "Pass Distributed Systems Exam"
    assert goal_mem_item["created_at"] is not None

    # 6. Filter by category
    res_weakness = await client.get("/api/v1/memories?category=Learned weakness", headers=headers_a)
    assert res_weakness.status_code == 200
    w_data = res_weakness.json()
    assert w_data["total"] == 1
    assert w_data["items"][0]["category"] == "Learned weakness"
    assert "Log Compaction" in w_data["items"][0]["source_details"]["raw_metadata"]["topic"]

    # 7. Inspect source provenance
    res_source = await client.get(f"/api/v1/memories/{mem_weakness.id}/source", headers=headers_a)
    assert res_source.status_code == 200
    src_data = res_source.json()
    assert src_data["source_name"] == "agent_learning_loop"
    assert src_data["domain"] == "Distributed Systems"
    assert src_data["topic"] == "Log Compaction"
    assert src_data["epistemic_qualifier"] == "Provisional hypothesis"
    assert src_data["is_hypothesis"] is True

    # 8. Correct memory
    correction_payload = {
        "content": "Log compaction corner cases resolved after implementing follower snapshot chunking RPC",
        "confidence": 0.96,
        "category": "Past outcome",
    }
    res_correct = await client.patch(
        f"/api/v1/memories/{mem_weakness.id}",
        json=correction_payload,
        headers=headers_a,
    )
    assert res_correct.status_code == 200
    corrected_data = res_correct.json()
    assert corrected_data["memory"] == correction_payload["content"]
    assert corrected_data["confidence"] == 0.96
    assert corrected_data["category"] == "Past outcome"
    assert corrected_data["source_details"]["user_corrected"] is True
    assert (
        corrected_data["source_details"]["original_content"]
        == "Struggles with log compaction and snapshotting corner cases under network partition"
    )

    # 9. Delete memory
    res_delete = await client.delete(f"/api/v1/memories/{mem_knowledge.id}", headers=headers_a)
    assert res_delete.status_code == 200
    assert res_delete.json()["success"] is True

    # Confirm deleted
    res_after_del = await client.get("/api/v1/memories", headers=headers_a)
    assert res_after_del.json()["total"] == 4

    # 10. Strict Multi-Tenant Isolation
    # User B cannot see User A's memories
    res_b_list = await client.get("/api/v1/memories", headers=headers_b)
    assert res_b_list.status_code == 200
    b_data = res_b_list.json()
    assert b_data["total"] == 1
    assert b_data["items"][0]["id"] == str(mem_user_b.id)

    # User B cannot get, correct, or delete User A's memory
    res_idor_get = await client.get(f"/api/v1/memories/{mem_goal.id}", headers=headers_b)
    assert res_idor_get.status_code == 404

    res_idor_patch = await client.patch(
        f"/api/v1/memories/{mem_goal.id}",
        json={"content": "Malicious edit"},
        headers=headers_b,
    )
    assert res_idor_patch.status_code == 404

    res_idor_del = await client.delete(f"/api/v1/memories/{mem_goal.id}", headers=headers_b)
    assert res_idor_del.status_code == 404
