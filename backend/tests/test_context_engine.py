import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal, GoalConstraint, GoalPriority, GoalStatus
from app.db.models.memory import Memory, MemoryStatus, MemoryType
from app.db.models.task import Task, TaskStatus
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.main import app
from app.services.context_engine import (
    BuiltContext,
    ContextBudget,
    ContextBuilder,
    ContextItem,
    ContextSource,
    count_tokens,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def test_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def other_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
async def session_factory() -> async_sessionmaker:
    """Create in-memory SQLite engine with fresh schema for Context Engine tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def db_session(session_factory: async_sessionmaker) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"context_test_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="mockhashedpassword123",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def test_token_counter_and_tokenizer():
    """Verify tokenizer estimates tokens accurately with tiktoken and heuristic fallback."""
    short_text = "Hello world"
    tokens = count_tokens(short_text)
    assert tokens >= 2

    long_text = "LifeThread autonomous agent context engine test. " * 50
    long_tokens = count_tokens(long_text)
    assert long_tokens > 200


def test_context_priority_ordering(test_user_id: uuid.UUID):
    """Verify that all 7 context sources are strictly ordered by priority (1 to 7)."""
    now = datetime.now(UTC)

    # Candidate items in reverse/shuffled order
    items = [
        ContextItem(
            id="evt-1",
            source=ContextSource.HISTORICAL_EVENTS,
            content="Event: Milestone 1 completed 2 weeks ago.",
            user_id=test_user_id,
            source_attribution="Event #1",
            timestamp=now - timedelta(days=14),
        ),
        ContextItem(
            id="doc-1",
            source=ContextSource.DOCUMENTS,
            content="Doc: System design specification sheet.",
            user_id=test_user_id,
            source_attribution="Doc: spec.pdf (Chunk 1)",
            timestamp=now - timedelta(days=2),
        ),
        ContextItem(
            id="mem-1",
            source=ContextSource.MEMORIES,
            content="Memory: User prefers concise TypeScript solutions.",
            user_id=test_user_id,
            source_attribution="Memory #pref-1",
            timestamp=now - timedelta(days=5),
        ),
        ContextItem(
            id="conv-1",
            source=ContextSource.CONVERSATION,
            content="User: Can you check the database migrations?",
            user_id=test_user_id,
            source_attribution="Conversation Turn 1",
            timestamp=now - timedelta(minutes=10),
        ),
        ContextItem(
            id="cons-1",
            source=ContextSource.CONSTRAINTS,
            content="Constraint: Maximum latency must not exceed 200ms.",
            user_id=test_user_id,
            source_attribution="Constraint #lat-1",
            timestamp=now - timedelta(days=1),
        ),
        ContextItem(
            id="goal-1",
            source=ContextSource.CURRENT_GOAL,
            content="Goal: Deploy Production Backend v1.0.",
            user_id=test_user_id,
            source_attribution="Goal #goal-1",
            timestamp=now - timedelta(days=3),
        ),
        ContextItem(
            id="task-1",
            source=ContextSource.CURRENT_TASK,
            content="Task: Write unit tests for Context Engine.",
            user_id=test_user_id,
            source_attribution="Current Task #task-1",
            timestamp=now - timedelta(minutes=5),
        ),
    ]

    builder = ContextBuilder(default_budget=ContextBudget(total_tokens=2000))
    result = builder.build(user_id=test_user_id, items=items)

    assert len(result.items) == 7
    # Verify exact priority sequence in final built items:
    # 1. Current task, 2. Current goal, 3. Constraints, 4. Conversation, 5. Memories, 6. Documents, 7. Events
    expected_order = [
        ContextSource.CURRENT_TASK,
        ContextSource.CURRENT_GOAL,
        ContextSource.CONSTRAINTS,
        ContextSource.CONVERSATION,
        ContextSource.MEMORIES,
        ContextSource.DOCUMENTS,
        ContextSource.HISTORICAL_EVENTS,
    ]
    actual_order = [it.source for it in result.items]
    assert actual_order == expected_order

    # Verify prompt formatting contains sections in order
    assert "## Current Task" in result.formatted_prompt
    assert "## Current Goal State" in result.formatted_prompt
    assert "## Current Constraints" in result.formatted_prompt
    assert "## Recent Relevant Conversation" in result.formatted_prompt
    assert "## Relevant Memories" in result.formatted_prompt
    assert "## Relevant Documents" in result.formatted_prompt
    assert "## Relevant Historical Events" in result.formatted_prompt


def test_context_budgeting_truncation(test_user_id: uuid.UUID):
    """Given a large amount of historical information, verify context stays strictly within budget."""
    now = datetime.now(UTC)

    # 1 High priority Task (approx 15 tokens)
    task_item = ContextItem(
        id="task-core",
        source=ContextSource.CURRENT_TASK,
        content="Task: Run benchmark suite and verify zero memory leaks.",
        user_id=test_user_id,
        source_attribution="Task #1",
        timestamp=now,
    )

    # 20 Historical Events with substantial text (each approx 30 tokens = 600 tokens)
    historical_items = [
        ContextItem(
            id=f"hist-{i}",
            source=ContextSource.HISTORICAL_EVENTS,
            content=f"Historical Event {i}: The system was rebooted and load test {i} was executed successfully with all nodes healthy.",
            user_id=test_user_id,
            source_attribution=f"History #{i}",
            timestamp=now - timedelta(hours=i),
            relevance_score=0.5,
        )
        for i in range(20)
    ]

    all_items = [task_item] + historical_items

    # Define tight budget of 100 tokens
    budget = ContextBudget(total_tokens=100)
    builder = ContextBuilder()
    result = builder.build(user_id=test_user_id, items=all_items, budget=budget)

    # Must stay within 100 tokens
    assert result.total_tokens <= 100
    assert result.total_tokens > 0

    # High priority task must be included
    item_ids = [it.id for it in result.items]
    assert "task-core" in item_ids

    # Excess historical items must have been dropped
    assert result.dropped_items_count > 10
    assert len(result.items) < len(all_items)


def test_per_source_max_and_reserved_budget(test_user_id: uuid.UUID):
    """Verify per-source reserved budgets guarantee allocation and max caps prevent starvation."""
    now = datetime.now(UTC)

    # Create 3 large document items (each ~50 tokens)
    docs = [
        ContextItem(
            id=f"doc-{i}",
            source=ContextSource.DOCUMENTS,
            content=f"Document chunk {i}: Exhaustive architectural analysis and benchmarking data detailing throughput patterns and caching strategies across cluster nodes {i}.",
            user_id=test_user_id,
            source_attribution=f"Doc #{i}",
            timestamp=now,
            relevance_score=0.9,
        )
        for i in range(3)
    ]

    # Create 1 memory item (~20 tokens)
    mem = ContextItem(
        id="mem-1",
        source=ContextSource.MEMORIES,
        content="User prefers PostgreSQL over MongoDB for persistence.",
        user_id=test_user_id,
        source_attribution="Memory #1",
        timestamp=now,
        relevance_score=0.8,
    )

    # Budget has cap on DOCUMENTS of 35 tokens (only 1 doc should fit, 2nd doc would exceed 35)
    # and reserve on MEMORIES of 30 tokens
    budget = ContextBudget(
        total_tokens=500,
        max_tokens_per_source={ContextSource.DOCUMENTS: 35},
        reserved_tokens_per_source={ContextSource.MEMORIES: 30},
    )

    builder = ContextBuilder()
    result = builder.build(user_id=test_user_id, items=docs + [mem], budget=budget)

    included_sources = [it.source for it in result.items]
    doc_count = included_sources.count(ContextSource.DOCUMENTS)
    assert doc_count == 1  # 2nd doc would exceed 35 token source cap
    assert "mem-1" in [it.id for it in result.items]


def test_strict_multi_tenant_user_isolation(test_user_id: uuid.UUID, other_user_id: uuid.UUID):
    """Verify that items belonging to other users are rejected immediately and never leak."""
    now = datetime.now(UTC)

    items = [
        ContextItem(
            id="user-task",
            source=ContextSource.CURRENT_TASK,
            content="Task for target user.",
            user_id=test_user_id,
            source_attribution="Target User Task",
            timestamp=now,
        ),
        ContextItem(
            id="other-user-secret-task",
            source=ContextSource.CURRENT_TASK,
            content="CRITICAL SECRET: Target user must never see other user's confidential goal.",
            user_id=other_user_id,
            source_attribution="Other User Confidential",
            relevance_score=1.0,
            timestamp=now,
        ),
        ContextItem(
            id="other-user-doc",
            source=ContextSource.DOCUMENTS,
            content="Other user private document.",
            user_id=other_user_id,
            source_attribution="Other User Doc",
            timestamp=now,
        ),
    ]

    builder = ContextBuilder(default_budget=ContextBudget(total_tokens=2000))
    result = builder.build(user_id=test_user_id, items=items)

    assert len(result.items) == 1
    assert result.items[0].id == "user-task"
    assert "CRITICAL SECRET" not in result.formatted_prompt
    assert "other-user-secret-task" not in [it.id for it in result.items]


def test_content_deduplication(test_user_id: uuid.UUID):
    """Verify duplicate text content is deduplicated, keeping higher priority source."""
    now = datetime.now(UTC)

    duplicate_content = (
        "Remember to always run automated migrations before starting the web server."
    )

    items = [
        # Memory with priority 5
        ContextItem(
            id="mem-dup",
            source=ContextSource.MEMORIES,
            content=duplicate_content,
            user_id=test_user_id,
            source_attribution="Memory #1",
            timestamp=now - timedelta(days=3),
        ),
        # Constraint with priority 3 (higher priority than memory)
        ContextItem(
            id="cons-dup",
            source=ContextSource.CONSTRAINTS,
            content="remember to always run automated migrations before starting the web server.",
            user_id=test_user_id,
            source_attribution="Constraint #1",
            timestamp=now,
        ),
        # Conversation with priority 4
        ContextItem(
            id="conv-dup",
            source=ContextSource.CONVERSATION,
            content="Remember to always run automated migrations before starting the web server.   ",
            user_id=test_user_id,
            source_attribution="Conversation #1",
            timestamp=now,
        ),
    ]

    builder = ContextBuilder(default_budget=ContextBudget(total_tokens=2000))
    result = builder.build(user_id=test_user_id, items=items)

    # Only 1 instance should remain
    assert len(result.items) == 1
    # The winner must be the Constraint (priority 3)
    assert result.items[0].id == "cons-dup"
    assert result.items[0].source == ContextSource.CONSTRAINTS


def test_relevance_scoring_and_threshold_filtering(test_user_id: uuid.UUID):
    """Verify candidate items are scored against query and low-relevance items are filtered."""
    now = datetime.now(UTC)

    items = [
        ContextItem(
            id="mem-relevant",
            source=ContextSource.MEMORIES,
            content="The customer specifically requested Dark Mode and high contrast themes.",
            user_id=test_user_id,
            source_attribution="Memory #themes",
            timestamp=now,
            relevance_score=0.5,
        ),
        ContextItem(
            id="mem-irrelevant",
            source=ContextSource.MEMORIES,
            content="Purchased office stationery supplies and paper clips.",
            user_id=test_user_id,
            source_attribution="Memory #supplies",
            timestamp=now - timedelta(days=30),
            relevance_score=0.1,
        ),
    ]

    builder = ContextBuilder()
    query = "dark mode theme configuration"

    # With threshold 0.35, the stationery memory should be pruned
    budget = ContextBudget(total_tokens=1000, min_relevance_threshold=0.35)
    result = builder.build(user_id=test_user_id, items=items, budget=budget, query=query)

    assert len(result.items) == 1
    assert result.items[0].id == "mem-relevant"
    assert result.items[0].relevance_score > 0.4


def test_deterministic_ordering(test_user_id: uuid.UUID):
    """Verify that multiple builds with permuted candidate lists produce identical output."""
    now = datetime.now(UTC)

    items_a = [
        ContextItem(
            id=f"item-{i}",
            source=ContextSource.MEMORIES,
            content=f"Fact number {i} regarding system configuration.",
            user_id=test_user_id,
            source_attribution=f"Fact #{i}",
            timestamp=now - timedelta(hours=i),
            relevance_score=0.8 - (i * 0.05),
        )
        for i in range(10)
    ]

    import random

    items_b = list(items_a)
    random.seed(42)
    random.shuffle(items_b)

    builder = ContextBuilder(default_budget=ContextBudget(total_tokens=1000))
    res_a = builder.build(user_id=test_user_id, items=items_a)
    res_b = builder.build(user_id=test_user_id, items=items_b)

    order_a = [it.id for it in res_a.items]
    order_b = [it.id for it in res_b.items]

    assert order_a == order_b
    assert res_a.formatted_prompt == res_b.formatted_prompt


@pytest.mark.asyncio
async def test_async_domain_context_builder(db_session: AsyncSession, test_user: User):
    """Verify build_from_domain gathers live domain entities (Goal, Task, Constraints, Memory)."""
    # 1. Create Goal with constraints
    goal = Goal(
        user_id=test_user.id,
        title="Automated Test Goal",
        objective="Verify context engine domain aggregation",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.HIGH,
    )
    db_session.add(goal)
    await db_session.flush()

    constraint = GoalConstraint(
        goal_id=goal.id,
        type="budget",
        value="Max monthly cost $50",
    )
    db_session.add(constraint)

    # 2. Create Task
    task = Task(
        goal_id=goal.id,
        title="Execute Unit Testing",
        description="Run test suite across all modules",
        status=TaskStatus.IN_PROGRESS,
        priority=GoalPriority.HIGH,
    )
    db_session.add(task)

    # 3. Create Memory
    mem = Memory(
        user_id=test_user.id,
        memory_type=MemoryType.PREFERENCE,
        content="Prefers pytest with verbose reporting",
        importance_score=0.9,
        confidence=1.0,
        source="user_preference",
        status=MemoryStatus.ACTIVE,
    )
    db_session.add(mem)
    await db_session.commit()

    # 4. Build context
    builder = ContextBuilder()
    conv = [
        {
            "role": "user",
            "content": "What are our current constraints?",
            "timestamp": datetime.now(UTC),
        }
    ]
    events = [{"title": "Sprint Planning", "description": "Planned Module 19 sprint deliverables"}]

    built = await builder.build_from_domain(
        db=db_session,
        user_id=test_user.id,
        task_id=task.id,
        goal_id=goal.id,
        conversation_history=conv,
        historical_events=events,
        budget=ContextBudget(total_tokens=3000),
    )

    assert isinstance(built, BuiltContext)
    assert built.total_tokens > 0

    sources = [it.source for it in built.items]
    assert ContextSource.CURRENT_TASK in sources
    assert ContextSource.CURRENT_GOAL in sources
    assert ContextSource.CONSTRAINTS in sources
    assert ContextSource.CONVERSATION in sources
    assert ContextSource.MEMORIES in sources
    assert ContextSource.HISTORICAL_EVENTS in sources

    # Check formatted prompt contains all section headers
    assert "## Current Task" in built.formatted_prompt
    assert "## Current Goal State" in built.formatted_prompt
    assert "## Current Constraints" in built.formatted_prompt
    assert "Max monthly cost $50" in built.formatted_prompt


@pytest.mark.asyncio
async def test_api_context_build_endpoint(db_session: AsyncSession, test_user: User):
    """Test the POST /api/v1/context/build API endpoint."""
    # Create an active goal
    goal = Goal(
        user_id=test_user.id,
        title="API Integration Test Goal",
        objective="Ensure API context endpoint returns structured response",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.MEDIUM,
    )
    db_session.add(goal)
    await db_session.commit()

    token, _, _ = create_access_token(subject=str(test_user.id))

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: test_user

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/context/build",
                json={
                    "goal_id": str(goal.id),
                    "query": "integration endpoint",
                    "total_tokens": 1500,
                    "conversation_history": [
                        {"role": "user", "content": "Let's test the context endpoint."}
                    ],
                },
                headers={"Authorization": f"Bearer {token}"},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert "items" in data
            assert "total_tokens" in data
            assert "formatted_prompt" in data
            assert data["token_budget"] == 1500
            assert "current_goal" in data["sources_included"]
    finally:
        app.dependency_overrides.clear()
