import uuid

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.memory import Memory, MemoryStatus, MemoryType
from app.db.models.task import GoalDecomposition, Task, TaskStatus
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.main import app
from app.services.context_engine.builder import ContextBuilder
from app.services.context_engine.models import ContextBudget, ContextSource
from app.services.learning import (
    AgentLearningLoopEngine,
    ExecutionOutcome,
    ExecutionStatus,
    LearningPlanningResult,
    LearningType,
    OutcomeEvaluation,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"learn_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="mockpassword",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ==============================================================================
# Test 1: Full Loop: Action -> Result -> Evaluation -> Memory -> Future Decision
# ==============================================================================
@pytest.mark.asyncio
async def test_action_result_evaluation_memory_loop(db_session: AsyncSession, test_user: User):
    """Loop Test:
    Action (Task: SQL practice)
    -> Result (Low performance: 0.35)
    -> Evaluation (Weakness in joins)
    -> Memory (User struggles with SQL joins)
    -> Future Decision (Increase SQL joins practice duration and priority).
    """
    # 1. Action & Result
    outcome = ExecutionOutcome(
        user_id=test_user.id,
        task_title="SQL practice",
        domain="SQL",
        topic="joins",
        action_type="TASK_EXECUTION",
        status=TaskStatus.COMPLETED,
        performance_score=0.35,
        actual_minutes=60,
        expected_minutes=60,
        notes="Struggled with complex inner and outer joins; ambiguous column errors.",
        attempt_count=2,
    )

    # 2. Evaluation & Memory Conversion
    eval_result, memory = await AgentLearningLoopEngine.record_and_learn(
        db=db_session,
        outcome=outcome,
    )

    assert isinstance(eval_result, OutcomeEvaluation)
    assert eval_result.is_meaningful is True
    assert eval_result.evaluation_type == LearningType.WEAKNESS
    assert "joins" in eval_result.observed_finding.lower()
    assert eval_result.confidence >= 0.70
    assert eval_result.is_factual is True

    # 3. Assert Memory Persisted
    assert memory is not None
    assert memory.memory_type == MemoryType.SEMANTIC
    assert "User struggles with SQL joins" in memory.content
    assert memory.metadata_json["domain"] == "SQL"
    assert memory.metadata_json["topic"] == "joins"
    assert memory.metadata_json["learning_type"] == "WEAKNESS"

    # 4. Future Decision: Planner inspects memory and increases SQL joins practice
    goal = Goal(
        user_id=test_user.id,
        title="Database Engineering Mastery",
        objective="Master relational queries and schema optimization",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.HIGH,
    )
    db_session.add(goal)
    await db_session.flush()

    task1 = Task(
        goal_id=goal.id,
        title="SQL joins practice exercise",
        status=TaskStatus.PENDING,
        priority=GoalPriority.MEDIUM,
        estimated_minutes=60,
        version=1,
    )
    task2 = Task(
        goal_id=goal.id,
        title="Database normalization basics",
        status=TaskStatus.PENDING,
        priority=GoalPriority.MEDIUM,
        estimated_minutes=45,
        version=1,
    )
    db_session.add_all([task1, task2])
    await db_session.commit()

    planning_result = await AgentLearningLoopEngine.apply_learnings_to_planner(
        db=db_session,
        user_id=test_user.id,
        goal_id=goal.id,
        tasks=[task1, task2],
        commit=True,
    )

    assert isinstance(planning_result, LearningPlanningResult)
    assert planning_result.tasks_modified_count == 1
    assert len(planning_result.memories_applied) >= 1
    impact = planning_result.memories_applied[0]
    assert impact.target_task_title == "SQL joins practice exercise"
    assert impact.adjustment_type == "INCREASE_PRACTICE"
    # Task duration was increased to allow extra practice for struggling area
    assert task1.estimated_minutes == 120  # doubled from 60 to 120
    assert task1.priority in (GoalPriority.HIGH, GoalPriority.CRITICAL)


# ==============================================================================
# Test 2: Meaningful Outcomes Only Converted (Requirement 1 & 2)
# ==============================================================================
@pytest.mark.asyncio
async def test_meaningful_outcomes_only_converted(db_session: AsyncSession, test_user: User):
    """Requirement 1 & 2: Routine expected runs with standard metrics do not pollute memory,

    whereas significant performance deviations or explicit notes are converted.
    """
    # Case A: Routine, expected run
    routine_outcome = ExecutionOutcome(
        user_id=test_user.id,
        task_title="Standard documentation review",
        status=TaskStatus.COMPLETED,
        performance_score=0.75,
        actual_minutes=30,
        expected_minutes=30,
        notes="All standard items completed on schedule.",
    )

    eval_routine, mem_routine = await AgentLearningLoopEngine.record_and_learn(
        db=db_session,
        outcome=routine_outcome,
    )
    assert eval_routine.is_meaningful is False
    assert mem_routine is None  # No memory created for routine execution

    # Case B: Significant failure / weakness outcome
    critical_outcome = ExecutionOutcome(
        user_id=test_user.id,
        task_title="Implement Redis caching",
        domain="System Design",
        topic="caching",
        status=ExecutionStatus.FAILED,
        error_message="Connection pool exhausted under concurrency load",
        performance_score=0.20,
    )
    eval_crit, mem_crit = await AgentLearningLoopEngine.record_and_learn(
        db=db_session,
        outcome=critical_outcome,
    )
    assert eval_crit.is_meaningful is True
    assert mem_crit is not None
    assert mem_crit.importance_score >= 0.70


# ==============================================================================
# Test 3: Confidence Assignment & Epistemic Qualifiers (Requirement 3 & 8)
# ==============================================================================
@pytest.mark.asyncio
async def test_assign_confidence_and_epistemic_qualifiers(
    db_session: AsyncSession, test_user: User
):
    """Requirement 3 & 8: High certainty test yields high confidence and verified fact,

    while ambiguous or single trial yields lower confidence marked as provisional hypothesis.
    """
    # Single trial with low sample (unverified)
    unverified_outcome = ExecutionOutcome(
        user_id=test_user.id,
        task_title="Exploratory Rust programming",
        domain="Rust",
        topic="borrow checker",
        status=TaskStatus.COMPLETED,
        notes="Felt confused about lifetime annotations once",
        attempt_count=1,
    )
    eval_unv, mem_unv = await AgentLearningLoopEngine.record_and_learn(
        db=db_session,
        outcome=unverified_outcome,
    )
    assert eval_unv.confidence < 0.70
    assert eval_unv.is_factual is False
    assert eval_unv.is_hypothesis is True
    assert "Hypothesis:" in mem_unv.content
    assert mem_unv.metadata_json["is_factual"] is False
    assert mem_unv.metadata_json["is_hypothesis"] is True


# ==============================================================================
# Test 4: Never Treat Uncertain Information as Fact (Requirement 8)
# ==============================================================================
@pytest.mark.asyncio
async def test_never_treat_uncertain_information_as_fact(db_session: AsyncSession, test_user: User):
    """Requirement 8: Ensure uncertain information is never treated as fact in memories or planning."""
    outcome = ExecutionOutcome(
        user_id=test_user.id,
        task_title="Data Structures practice",
        domain="Python",
        topic="recursion",
        performance_score=0.55,
        notes="Uncertain trial; single attempt with confusing prompt",
        attempt_count=1,
    )
    eval_res, mem = await AgentLearningLoopEngine.record_and_learn(
        db=db_session,
        outcome=outcome,
    )
    assert mem is not None
    assert mem.metadata_json["is_factual"] is False
    assert mem.metadata_json["is_hypothesis"] is True
    assert "Hypothesis:" in mem.content
    # Confidence must reflect uncertainty
    assert mem.confidence < 0.70


# ==============================================================================
# Test 5: Avoid Duplicate Memories & Reinforce (Requirement 4)
# ==============================================================================
@pytest.mark.asyncio
async def test_avoid_duplicate_memories(db_session: AsyncSession, test_user: User):
    """Requirement 4: Repeating an outcome reinforces existing memory without duplicate rows."""
    outcome1 = ExecutionOutcome(
        user_id=test_user.id,
        task_title="SQL joins practice",
        domain="SQL",
        topic="joins",
        performance_score=0.30,
        notes="Struggled with joins",
        attempt_count=1,
    )
    _, mem1 = await AgentLearningLoopEngine.record_and_learn(db=db_session, outcome=outcome1)
    assert mem1 is not None
    initial_mem_id = mem1.id
    initial_access_count = mem1.access_count

    # Second outcome on the same topic and finding
    outcome2 = ExecutionOutcome(
        user_id=test_user.id,
        task_title="SQL joins quiz 2",
        domain="SQL",
        topic="joins",
        performance_score=0.35,
        notes="Still struggling with complex joins",
        attempt_count=2,
    )
    _, mem2 = await AgentLearningLoopEngine.record_and_learn(db=db_session, outcome=outcome2)

    # Must point to identical memory record (no duplicate created)
    assert mem2.id == initial_mem_id
    assert mem2.access_count == initial_access_count + 1
    assert mem2.confidence >= mem1.confidence

    # Verify DB only has 1 active memory
    mem_q = select(Memory).where(
        Memory.user_id == test_user.id, Memory.status == MemoryStatus.ACTIVE
    )
    mem_res = await db_session.execute(mem_q)
    active_mems = mem_res.scalars().all()
    assert len(active_mems) == 1


# ==============================================================================
# Test 6: Update Outdated Memories (Requirement 5)
# ==============================================================================
@pytest.mark.asyncio
async def test_update_outdated_memories(db_session: AsyncSession, test_user: User):
    """Requirement 5: When new outcome contradicts an old memory (e.g. mastery replaces weakness),

    the outdated memory is marked SUPERSEDED and updated memory is stored.
    """
    # 1. User initially struggles
    weakness_outcome = ExecutionOutcome(
        user_id=test_user.id,
        task_title="Docker deployment practice",
        domain="DevOps",
        topic="dockerfile",
        performance_score=0.30,
        notes="Failed multi-stage build optimization",
        attempt_count=2,
    )
    _, old_mem = await AgentLearningLoopEngine.record_and_learn(
        db=db_session, outcome=weakness_outcome
    )
    assert old_mem.status == MemoryStatus.ACTIVE
    assert "struggles with" in old_mem.content

    # 2. Later, user masters the topic with 95% score
    mastery_outcome = ExecutionOutcome(
        user_id=test_user.id,
        task_title="Advanced Docker deployment assessment",
        domain="DevOps",
        topic="dockerfile",
        performance_score=0.95,
        notes="Successfully optimized multi-stage build with zero errors",
        attempt_count=3,
    )
    _, new_mem = await AgentLearningLoopEngine.record_and_learn(
        db=db_session, outcome=mastery_outcome
    )

    await db_session.refresh(old_mem)
    # Old weakness memory must be SUPERSEDED
    assert old_mem.status == MemoryStatus.SUPERSEDED
    assert old_mem.metadata_json["superseded_by_outcome_id"] == mastery_outcome.outcome_id

    # New memory must be ACTIVE reflecting mastery
    assert new_mem.id != old_mem.id
    assert new_mem.status == MemoryStatus.ACTIVE
    assert "demonstrated proficiency" in new_mem.content


# ==============================================================================
# Test 7: Link Memories to Goals and Tasks (Requirement 6)
# ==============================================================================
@pytest.mark.asyncio
async def test_link_memories_to_goals_and_tasks(db_session: AsyncSession, test_user: User):
    """Requirement 6: Memories retain provenance links to goals, tasks, and topics."""
    goal = Goal(
        id=uuid.uuid4(),
        user_id=test_user.id,
        title="Distributed locks learning goal",
        objective="Learn distributed locks and concurrency",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.MEDIUM,
    )
    db_session.add(goal)
    await db_session.commit()
    await db_session.refresh(goal)
    goal_id = goal.id
    task_id = uuid.uuid4()

    outcome = ExecutionOutcome(
        user_id=test_user.id,
        goal_id=goal_id,
        task_id=task_id,
        task_title="Distributed locks with Redis",
        domain="System Design",
        topic="concurrency",
        performance_score=0.25,
        notes="Encountered race conditions and lock timeouts",
        attempt_count=2,
    )

    _, memory = await AgentLearningLoopEngine.record_and_learn(db=db_session, outcome=outcome)
    assert memory is not None
    meta = memory.metadata_json
    assert meta["goal_id"] == str(goal_id)
    assert meta["task_id"] == str(task_id)
    assert meta["domain"] == "System Design"
    assert meta["topic"] == "concurrency"

    # Query by goal_id and task_id
    filtered = await AgentLearningLoopEngine.get_learning_memories(
        db=db_session,
        user_id=test_user.id,
        goal_id=goal_id,
        task_id=task_id,
    )
    assert len(filtered) == 1
    assert filtered[0].id == memory.id


# ==============================================================================
# Test 8: Context Engine Availability (Requirement 7)
# ==============================================================================
@pytest.mark.asyncio
async def test_make_memories_available_to_context_engine(db_session: AsyncSession, test_user: User):
    """Requirement 7: Retrieved learning memories convert to ContextItems and integrate into Context Engine."""
    outcome = ExecutionOutcome(
        user_id=test_user.id,
        task_title="Postgres Indexing Workshop",
        domain="SQL",
        topic="indexing",
        performance_score=0.92,
        notes="Mastered B-tree and GIN indexing strategies",
        attempt_count=2,
    )
    await AgentLearningLoopEngine.record_and_learn(db=db_session, outcome=outcome)

    # 1. Convert to ContextItems
    context_items = await AgentLearningLoopEngine.build_learning_context_items(
        db=db_session,
        user_id=test_user.id,
        query="indexing",
    )
    assert len(context_items) >= 1
    c_item = context_items[0]
    assert c_item.source == ContextSource.MEMORIES
    assert "indexing" in c_item.content.lower()

    # 2. Feed into ContextBuilder
    builder = ContextBuilder(default_budget=ContextBudget(total_tokens=1000, memories_tokens=400))
    built_ctx = builder.build(
        items=context_items,
        user_id=test_user.id,
        query="database performance",
    )
    assert built_ctx.total_tokens > 0
    assert ContextSource.MEMORIES.value in built_ctx.sources_included
    assert "indexing" in built_ctx.formatted_prompt.lower()


# ==============================================================================
# Test 9: Acceptance Criteria: Earlier Run Affects Later Planning Decision
# ==============================================================================
@pytest.mark.asyncio
async def test_acceptance_criteria_earlier_run_affects_later_planning_decision(
    db_session: AsyncSession, test_user: User
):
    """ACCEPTANCE CRITERIA:

    A result from an earlier agent run can affect a later planning decision through persisted memory.
    """
    # -------------------------------------------------------------
    # Agent Run 1: Task executes, produces low performance, persists memory
    # -------------------------------------------------------------
    run_1_outcome = ExecutionOutcome(
        user_id=test_user.id,
        task_title="SQL practice",
        domain="SQL",
        topic="joins",
        action_type="TASK_EXECUTION",
        status=TaskStatus.COMPLETED,
        performance_score=0.35,
        notes="Low performance on SQL joins",
        attempt_count=2,
    )
    eval_1, mem_1 = await AgentLearningLoopEngine.record_and_learn(
        db=db_session,
        outcome=run_1_outcome,
    )
    assert mem_1 is not None
    assert "User struggles with SQL joins" in mem_1.content

    # -------------------------------------------------------------
    # Agent Run 2: Later planning run for a new goal
    # -------------------------------------------------------------
    new_goal = Goal(
        user_id=test_user.id,
        title="Full Stack Analytics Platform",
        objective="Deploy backend analytics pipeline",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.HIGH,
    )
    db_session.add(new_goal)
    await db_session.flush()

    decomp = GoalDecomposition(goal_id=new_goal.id, version=1, is_active=True)
    db_session.add(decomp)
    await db_session.flush()

    planned_task = Task(
        goal_id=new_goal.id,
        title="Write SQL queries with joins",
        status=TaskStatus.PENDING,
        priority=GoalPriority.MEDIUM,
        estimated_minutes=45,
        version=1,
    )
    db_session.add(planned_task)
    await db_session.commit()

    # Apply learnings to future planner
    planning_res = await AgentLearningLoopEngine.apply_learnings_to_planner(
        db=db_session,
        user_id=test_user.id,
        goal_id=new_goal.id,
        tasks=[planned_task],
        commit=True,
    )

    # Assert later planning decision was affected by Run 1 memory
    assert planning_res.relevant_memories_count >= 1
    assert planning_res.tasks_modified_count == 1
    assert planned_task.estimated_minutes == 90  # doubled from 45 to 90
    assert planned_task.priority in (GoalPriority.HIGH, GoalPriority.CRITICAL)
    assert "User struggles with SQL joins" in planning_res.summary_rationale


# ==============================================================================
# Test 10: API Learning Endpoints
# ==============================================================================
@pytest.mark.asyncio
async def test_api_learning_endpoints(engine, session_factory):
    """Test REST API endpoints /api/v1/learning/outcome, /memories, /apply-to-plan."""
    async with session_factory() as session:
        user = User(
            id=uuid.uuid4(),
            email="api_learning_user@example.com",
            password_hash="mockpass",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        user_id = user.id

    token = create_access_token(subject=user_id)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def override_get_current_user():
        async with session_factory() as session:
            res = await session.execute(select(User).where(User.id == user_id))
            return res.scalar_one()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_get_current_user

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {token}"}

            # 1. POST /api/v1/learning/outcome
            outcome_payload = {
                "user_id": str(user_id),
                "task_title": "SQL practice",
                "domain": "SQL",
                "topic": "joins",
                "performance_score": 0.35,
                "notes": "Low performance in SQL joins",
                "attempt_count": 2,
            }
            resp = await client.post(
                "/api/v1/learning/outcome", json=outcome_payload, headers=headers
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["memory_created"] is True
            assert "User struggles with SQL joins" in data["memory_content"]

            # 2. GET /api/v1/learning/memories
            resp_mems = await client.get("/api/v1/learning/memories?domain=SQL", headers=headers)
            assert resp_mems.status_code == 200
            mems = resp_mems.json()
            assert len(mems) >= 1
            assert "joins" in mems[0]["content"].lower()

            # 3. Create Goal and Task, then POST /api/v1/learning/apply-to-plan
            async with session_factory() as session:
                g = Goal(user_id=user_id, title="Analytics", objective="Data analysis")
                session.add(g)
                await session.flush()
                t = Task(goal_id=g.id, title="SQL joins exercises", estimated_minutes=50, version=1)
                session.add(t)
                await session.commit()
                goal_id = g.id

            apply_resp = await client.post(
                "/api/v1/learning/apply-to-plan",
                json={"goal_id": str(goal_id), "commit": True},
                headers=headers,
            )
            assert apply_resp.status_code == 200
            plan_data = apply_resp.json()
            assert plan_data["tasks_modified_count"] == 1
    finally:
        app.dependency_overrides.clear()
