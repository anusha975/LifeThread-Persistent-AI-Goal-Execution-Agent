import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.db.base import Base
from app.db.models.memory import MemoryStatus, MemoryType
from app.schemas.memory import MemoryCreate, MemoryUpdate
from app.services.memory import MemoryService
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory() -> async_sessionmaker:
    """Create in-memory SQLite engine with fresh schema for Memory Engine tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_all_four_memory_types(session_factory: async_sessionmaker) -> None:
    """Requirement: Implement Episodic, Semantic, Goal, and Preference memory types."""
    user_id = uuid.uuid4()

    async with session_factory() as session:
        # 1. Episodic
        m_episodic = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="User completed task #42 ahead of time yesterday.",
                memory_type=MemoryType.EPISODIC,
                importance_score=0.7,
                confidence=0.95,
                source="observation:orchestrator",
                metadata={"task_id": "42"},
            ),
        )
        # 2. Semantic
        m_semantic = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="PyTorch lightning simplifies distributed DDP setup.",
                memory_type=MemoryType.SEMANTIC,
                importance_score=0.8,
                confidence=1.0,
                source="documentation",
                metadata={"topic": "ai"},
            ),
        )
        # 3. Goal
        m_goal = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Goal constraint: budget cannot exceed $500/month.",
                memory_type=MemoryType.GOAL,
                importance_score=0.9,
                confidence=1.0,
                source="user_prompt",
                metadata={"constraint_type": "budget"},
            ),
        )
        # 4. Preference
        m_pref = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="User prefers succinct responses with code diffs.",
                memory_type=MemoryType.PREFERENCE,
                importance_score=0.85,
                confidence=0.9,
                source="user_feedback",
                metadata={"category": "communication_style"},
            ),
        )
        await session.commit()

        # Verify all fields present and correct
        for m, expected_type in [
            (m_episodic, MemoryType.EPISODIC),
            (m_semantic, MemoryType.SEMANTIC),
            (m_goal, MemoryType.GOAL),
            (m_pref, MemoryType.PREFERENCE),
        ]:
            assert m.id is not None
            assert m.user_id == user_id
            assert m.type == expected_type
            assert m.memory_type == expected_type
            assert len(m.content) > 5
            assert len(m.source) > 0
            assert 0.0 <= m.importance <= 1.0
            assert 0.0 <= m.confidence <= 1.0
            assert m.created_at is not None
            assert m.updated_at is not None
            assert isinstance(m.metadata_json, dict)


@pytest.mark.asyncio
async def test_duplicate_detection_and_reinforcement(session_factory: async_sessionmaker) -> None:
    """Requirement: Duplicate detection and reinforcement."""
    user_id = uuid.uuid4()

    async with session_factory() as session:
        # First creation
        m1 = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="User prefers dark mode in all UI views",
                memory_type=MemoryType.PREFERENCE,
                importance_score=0.6,
                confidence=0.8,
                source="ui_settings",
            ),
        )
        await session.commit()
        m1_id = m1.id

        # Second creation with identical normalized content (different spacing/casing)
        m2 = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="  user prefers   dark mode in ALL ui views  ",
                memory_type=MemoryType.PREFERENCE,
                importance_score=0.85,
                confidence=0.95,
                source="user_chat",
                metadata={"source_detail": "chat_input"},
            ),
        )
        await session.commit()

        # Must return the SAME memory row with reinforced metrics
        assert m2.id == m1_id
        assert m2.access_count == 1
        assert m2.importance_score == 0.85  # Updated to max
        assert m2.confidence == 1.0  # Boosted on reinforcement
        assert "last_reinforced_at" in m2.metadata_json

        # Query all memories to verify only ONE record exists
        all_mems, count = await MemoryService.search_memories(db=session, user_id=user_id)
        assert count == 1
        assert len(all_mems) == 1


@pytest.mark.asyncio
async def test_user_isolation_security(session_factory: async_sessionmaker) -> None:
    """Requirement: Strict user isolation."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    async with session_factory() as session:
        m_a = await MemoryService.store_memory(
            db=session,
            user_id=user_a,
            create_data=MemoryCreate(
                content="Confidential API token details for user A",
                memory_type=MemoryType.SEMANTIC,
                source="vault",
            ),
        )
        await session.commit()

        # User B cannot retrieve User A's memory
        with pytest.raises(HTTPException) as exc_info:
            await MemoryService.get_memory_by_id(db=session, memory_id=m_a.id, user_id=user_b)
        assert exc_info.value.status_code == 404

        # User B cannot search User A's memory
        b_results, b_count = await MemoryService.search_memories(
            db=session, user_id=user_b, query="Confidential"
        )
        assert b_count == 0
        assert len(b_results) == 0

        # User B cannot update User A's memory
        with pytest.raises(HTTPException) as exc_info2:
            await MemoryService.update_memory(
                db=session,
                memory_id=m_a.id,
                user_id=user_b,
                update_data=MemoryUpdate(content="Tampered"),
            )
        assert exc_info2.value.status_code == 404

        # User B cannot delete User A's memory
        with pytest.raises(HTTPException) as exc_info3:
            await MemoryService.delete_memory(db=session, memory_id=m_a.id, user_id=user_b)
        assert exc_info3.value.status_code == 404


@pytest.mark.asyncio
async def test_retrieval_updates_access_tracking(session_factory: async_sessionmaker) -> None:
    """Requirement: Retrieval tracking and source provenance."""
    user_id = uuid.uuid4()

    async with session_factory() as session:
        created = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Key architecture insight regarding CQRS",
                memory_type=MemoryType.SEMANTIC,
                source="reflection:deep_think",
            ),
        )
        await session.commit()
        assert created.access_count == 0

        # Retrieve once
        retrieved1 = await MemoryService.get_memory_by_id(
            db=session, memory_id=created.id, user_id=user_id
        )
        await session.commit()
        assert retrieved1.access_count == 1
        assert retrieved1.last_accessed_at is not None

        # Retrieve second time
        retrieved2 = await MemoryService.get_memory_by_id(
            db=session, memory_id=created.id, user_id=user_id
        )
        await session.commit()
        assert retrieved2.access_count == 2


@pytest.mark.asyncio
async def test_structured_search_filters(session_factory: async_sessionmaker) -> None:
    """Requirement: Reliable retrieval using structured filters."""
    user_id = uuid.uuid4()

    async with session_factory() as session:
        # Seed 4 distinct memories
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Database connection pool size set to 20",
                memory_type=MemoryType.SEMANTIC,
                importance_score=0.9,
                confidence=1.0,
                source="config",
            ),
        )
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Database timeout occurred on replica 2",
                memory_type=MemoryType.EPISODIC,
                importance_score=0.5,
                confidence=0.8,
                source="error_log",
            ),
        )
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Goal deadline: ship Q3 release by end of month",
                memory_type=MemoryType.GOAL,
                importance_score=0.95,
                confidence=1.0,
                source="user",
            ),
        )
        await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="User dislikes noisy notification pings",
                memory_type=MemoryType.PREFERENCE,
                importance_score=0.7,
                confidence=0.85,
                source="user_preference",
            ),
        )
        await session.commit()

        # 1. Filter by query
        db_mems, total = await MemoryService.search_memories(
            db=session, user_id=user_id, query="Database"
        )
        assert total == 2
        for m in db_mems:
            assert "database" in m.content.lower()

        # 2. Filter by memory_type
        goal_mems, total_goals = await MemoryService.search_memories(
            db=session, user_id=user_id, memory_type=MemoryType.GOAL
        )
        assert total_goals == 1
        assert goal_mems[0].memory_type == MemoryType.GOAL

        # 3. Filter by min_importance (>= 0.8)
        high_imp, total_high = await MemoryService.search_memories(
            db=session, user_id=user_id, min_importance=0.8
        )
        assert total_high == 2
        for m in high_imp:
            assert m.importance_score >= 0.8

        # 4. Filter by min_confidence (>= 0.9)
        high_conf, total_conf = await MemoryService.search_memories(
            db=session, user_id=user_id, min_confidence=0.9
        )
        assert total_conf == 2


@pytest.mark.asyncio
async def test_memory_lifecycle_rules(session_factory: async_sessionmaker) -> None:
    """Requirement: Memory lifecycle rules (recency decay, preference protection, reinforcement)."""
    user_id = uuid.uuid4()

    async with session_factory() as session:
        # 1. Stale episodic memory older than 30 days with low importance (should archive or decay)
        stale_episodic = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Ephemeral build warning log from last month",
                memory_type=MemoryType.EPISODIC,
                importance_score=0.15,
                confidence=0.7,
            ),
        )
        stale_episodic.created_at = datetime.now(UTC) - timedelta(days=45)
        stale_episodic.access_count = 0

        # 2. Preference memory with low initial importance (should be protected >= 0.4)
        pref_mem = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="User prefers monospace font in terminal",
                memory_type=MemoryType.PREFERENCE,
                importance_score=0.25,
            ),
        )

        # 3. High access memory (access_count = 6, should be reinforced)
        frequent_mem = await MemoryService.store_memory(
            db=session,
            user_id=user_id,
            create_data=MemoryCreate(
                content="Core architectural guideline for service contracts",
                memory_type=MemoryType.SEMANTIC,
                importance_score=0.7,
            ),
        )
        frequent_mem.access_count = 6

        await session.commit()

        # Run lifecycle rules
        lifecycle_res = await MemoryService.apply_lifecycle_rules(
            db=session, user_id=user_id, retention_days=30
        )
        await session.commit()

        assert lifecycle_res.archived_count >= 1
        assert lifecycle_res.reinforced_count >= 1

        # Check individual outcomes
        await session.refresh(stale_episodic)
        await session.refresh(pref_mem)
        await session.refresh(frequent_mem)

        assert stale_episodic.status == MemoryStatus.ARCHIVED
        assert pref_mem.importance_score >= 0.4  # Protected from decay
        assert frequent_mem.importance_score == 0.75  # Boosted by +0.05
