import json
import uuid

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.task import Task, TaskStatus
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.main import app
from app.services.context_engine.models import ContextItem, ContextSource
from app.services.recovery import (
    FailureRecoveryEngine,
    RecoveryErrorCode,
    RetryPolicy,
    idempotency_manager,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
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
        email=f"recovery_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="mockpassword",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture(autouse=True)
def cleanup_recovery_state():
    idempotency_manager.clear()
    FailureRecoveryEngine.clear_notifications()
    yield
    idempotency_manager.clear()
    FailureRecoveryEngine.clear_notifications()


# ==============================================================================
# Test 1: LLM Timeout Recovery with Fallback
# ==============================================================================
@pytest.mark.asyncio
async def test_llm_timeout_recovery(test_user: User):
    """Test LLM timeout: Primary caller hangs/times out -> retries with backoff -> falls back to secondary provider."""
    call_counts = {"primary": 0, "fallback": 0}

    async def mock_primary_timeout():
        call_counts["primary"] += 1
        raise TimeoutError("OpenAI API call timed out after 30.0s")

    async def mock_secondary_fallback():
        call_counts["fallback"] += 1
        return json.dumps({"status": "SUCCESS", "message": "Fallback Claude model response"})

    result = await FailureRecoveryEngine.recover_llm_call(
        prompt="Decompose goal",
        user_id=test_user.id,
        primary_caller=mock_primary_timeout,
        fallback_caller=mock_secondary_fallback,
        policy=RetryPolicy(max_retries=2, base_delay_seconds=0.01),
    )

    assert result.success is True
    assert result.final_action == "RECOVERED_VIA_FALLBACK"
    assert result.fallback_applied is True
    assert call_counts["primary"] == 3  # Initial + 2 retries (bounded!)
    assert call_counts["fallback"] == 1
    assert "Fallback Claude model response" in result.data
    assert result.user_notification is not None


# ==============================================================================
# Test 2: LLM Malformed Response Recovery
# ==============================================================================
@pytest.mark.asyncio
async def test_llm_malformed_response_recovery(test_user: User):
    """Test LLM malformed response: Unparseable response triggers schema validator error -> repaired fallback."""
    attempt_count = 0

    async def mock_malformed_llm():
        nonlocal attempt_count
        attempt_count += 1
        # Returns unparseable broken markdown instead of valid JSON
        return "```json\n{ broken json missing closing brace:"

    def schema_validator(resp: str):
        # Enforces valid JSON
        json.loads(resp)

    async def fallback_repair_llm():
        return json.dumps({"status": "REPAIRED", "milestones": [{"title": "Phase 1"}]})

    result = await FailureRecoveryEngine.recover_llm_call(
        prompt="Generate plan",
        user_id=test_user.id,
        primary_caller=mock_malformed_llm,
        fallback_caller=fallback_repair_llm,
        schema_validator=schema_validator,
        policy=RetryPolicy(max_retries=1, base_delay_seconds=0.01),
    )

    assert result.success is True
    assert result.final_action == "RECOVERED_VIA_FALLBACK"
    parsed = json.loads(result.data)
    assert parsed["status"] == "REPAIRED"


# ==============================================================================
# Test 3: MCP Timeout Recovery with Local Fallback
# ==============================================================================
@pytest.mark.asyncio
async def test_mcp_timeout_recovery(test_user: User):
    """Test MCP timeout: Remote MCP server hangs -> retries with exponential backoff -> falls back to local tool."""
    mcp_calls = 0

    async def mock_mcp_caller(tool_name: str, args: dict):
        nonlocal mcp_calls
        mcp_calls += 1
        raise TimeoutError(f"MCP tool_call '{tool_name}' timed out after 10.0s")

    def local_fallback_tool(args: dict):
        return {"result": "local_offline_computation", "value": 42}

    result = await FailureRecoveryEngine.recover_mcp_call(
        tool_name="calculate_critical_path",
        arguments={"task_ids": ["t1", "t2"]},
        user_id=test_user.id,
        mcp_caller=mock_mcp_caller,
        fallback_local_tool=local_fallback_tool,
        policy=RetryPolicy(max_retries=2, base_delay_seconds=0.01),
    )

    assert result.success is True
    assert result.final_action == "RECOVERED_VIA_FALLBACK"
    assert result.fallback_applied is True
    assert result.data["result"] == "local_offline_computation"
    assert mcp_calls == 3  # Initial + 2 retries (strictly bounded)


# ==============================================================================
# Test 4: MCP Unavailable Recovery
# ==============================================================================
@pytest.mark.asyncio
async def test_mcp_unavailable_recovery(test_user: User):
    """Test MCP unavailable: 503 / connection refused -> retries -> degraded mode notification."""
    calls = 0

    async def mock_mcp_unavailable(tool_name: str, args: dict):
        nonlocal calls
        calls += 1
        raise ConnectionRefusedError("MCP Server 503: Service Unavailable on port 8000")

    result = await FailureRecoveryEngine.recover_mcp_call(
        tool_name="semantic_memory_search",
        arguments={"query": "test"},
        user_id=test_user.id,
        mcp_caller=mock_mcp_unavailable,
        policy=RetryPolicy(max_retries=2, base_delay_seconds=0.01),
    )

    assert result.success is True
    assert result.final_action == "RECOVERED_VIA_FALLBACK"
    assert result.data["status"] == "DEGRADED_MCP_FALLBACK"
    assert calls == 3


# ==============================================================================
# Test 5: Tool Failure Recovery with Transient Retry
# ==============================================================================
@pytest.mark.asyncio
async def test_tool_failure_recovery_transient_retry(test_user: User):
    """Test Tool failure: Tool fails twice on transient error, succeeds on 3rd attempt."""
    calls = 0

    async def flaky_tool(args: dict):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("Temporary network glitch during tool run")
        return {"status": "SUCCESS", "records_processed": 100}

    result = await FailureRecoveryEngine.recover_tool_execution(
        tool_name="process_dataset",
        arguments={"dataset_id": "ds_1"},
        user_id=test_user.id,
        executor_func=flaky_tool,
    )

    assert result.success is True
    assert result.final_action == "RECOVERED_VIA_RETRY"
    assert result.attempts_made == 3
    assert result.data["records_processed"] == 100


# ==============================================================================
# Test 6: Invalid Tool Arguments with Automated Repair
# ==============================================================================
@pytest.mark.asyncio
async def test_invalid_tool_arguments_repair(test_user: User):
    """Test Invalid tool arguments: Argument type error -> repaired by argument corrector."""

    def strict_tool(args: dict):
        if not isinstance(args.get("limit"), int):
            raise TypeError("Invalid tool argument: 'limit' must be an integer, got string.")
        return {"items": ["item1", "item2"][: args["limit"]]}

    def arg_corrector(args: dict) -> dict:
        repaired = dict(args)
        if "limit" in repaired:
            repaired["limit"] = int(repaired["limit"])
        return repaired

    result = await FailureRecoveryEngine.recover_tool_execution(
        tool_name="fetch_items",
        arguments={"limit": "2"},  # String instead of int
        user_id=test_user.id,
        executor_func=strict_tool,
        argument_corrector=arg_corrector,
    )

    assert result.success is True
    assert result.final_action == "RECOVERED_VIA_FALLBACK"
    assert len(result.data["items"]) == 2


# ==============================================================================
# Test 7: Database Transient Failure with Rollback & State Preservation
# ==============================================================================
@pytest.mark.asyncio
async def test_database_transient_failure_and_rollback(db_session: AsyncSession, test_user: User):
    """Test DB transient failure: Deadlock triggers rollback, keeping session and state uncorrupted, then succeeds."""
    goal = Goal(
        user_id=test_user.id,
        title="Initial State Goal",
        objective="Verify state uncorrupted",
        status=GoalStatus.ACTIVE,
    )
    db_session.add(goal)
    await db_session.commit()

    db_attempts = 0

    async def update_with_deadlock():
        nonlocal db_attempts
        db_attempts += 1
        # Modify goal in-memory
        goal.title = f"Dirty Title Attempt {db_attempts}"
        if db_attempts < 2:
            raise OperationalError("database is locked", {}, None)
        goal.title = "Final Clean Recovered Title"
        return goal.title

    result = await FailureRecoveryEngine.recover_db_transaction(
        db_session=db_session,
        user_id=test_user.id,
        tx_operation=update_with_deadlock,
    )

    assert result.success is True
    assert result.final_action == "RECOVERED_VIA_RETRY"
    assert result.attempts_made == 2
    assert goal.title == "Final Clean Recovered Title"


# ==============================================================================
# Test 8: Planning Failure with Rollback and Safe Fallback Plan
# ==============================================================================
@pytest.mark.asyncio
async def test_planning_failure_and_rollback(test_user: User):
    """Test Planning failure: Cyclical dependency raises error -> rollback partial state -> fallback baseline plan."""
    rolled_back = False

    async def invalid_planning_cycle():
        raise ValueError("PLANNING_FAILURE: Graph has a cycle (T1 -> T2 -> T1)")

    async def rollback_partial():
        nonlocal rolled_back
        rolled_back = True

    def fallback_linear_plan():
        return {"plan_version": 1, "is_feasible": True, "type": "LINEAR_FALLBACK"}

    goal_id = uuid.uuid4()
    result = await FailureRecoveryEngine.recover_planning(
        goal_id=goal_id,
        user_id=test_user.id,
        planning_op=invalid_planning_cycle,
        fallback_plan_generator=fallback_linear_plan,
        rollback_plan=rollback_partial,
    )

    assert result.success is True
    assert result.final_action == "RECOVERED_VIA_FALLBACK"
    assert result.fallback_applied is True
    assert rolled_back is True  # Rollback verified!
    assert result.data["type"] == "LINEAR_FALLBACK"


# ==============================================================================
# Test 9: Context Overflow Recovery with Progressive Pruning
# ==============================================================================
@pytest.mark.asyncio
async def test_context_overflow_recovery(test_user: User):
    """Test Context overflow: Tokens exceed limit -> progressively prunes lower-priority items to fit budget."""
    # 3 Items: High priority (1), Medium priority (3), Low priority (7)
    item_high = ContextItem(
        user_id=test_user.id,
        source=ContextSource.CURRENT_TASK,
        source_attribution="task",
        content="High priority active task specification",
        tokens=300,
        priority=1,
    )
    item_med = ContextItem(
        user_id=test_user.id,
        source=ContextSource.CONSTRAINTS,
        source_attribution="constraints",
        content="Medium priority deadline constraints",
        tokens=300,
        priority=3,
    )
    item_low = ContextItem(
        user_id=test_user.id,
        source=ContextSource.HISTORICAL_EVENTS,
        source_attribution="history",
        content="Low priority old historical log",
        tokens=600,
        priority=7,
    )

    all_items = [item_high, item_med, item_low]  # Total 1200 tokens

    def builder(items: list[ContextItem]):
        total = sum(i.tokens for i in items)
        return {"included_count": len(items), "total_tokens": total}

    # Target limit = 700 tokens (item_low must be pruned out)
    result = await FailureRecoveryEngine.recover_context_overflow(
        user_id=test_user.id,
        context_items=all_items,
        builder_func=builder,
        target_token_limit=700,
    )

    assert result.success is True
    assert result.final_action == "RECOVERED_VIA_FALLBACK"
    # item_high (300) + item_med (300) = 600 <= 700 tokens
    assert result.data["included_count"] == 2
    assert result.data["total_tokens"] == 600


# ==============================================================================
# Test 10: Idempotency Prevents Duplicate Actions (Requirement)
# ==============================================================================
@pytest.mark.asyncio
async def test_idempotency_prevents_duplicate_actions(test_user: User):
    """Requirement: Idempotent execution prevents duplicate actions or duplicate side effects."""
    action_counter = 0

    async def side_effect_action():
        nonlocal action_counter
        action_counter += 1
        return {"action_id": "act_123", "counter": action_counter}

    idemp_key = f"action:create_task:{uuid.uuid4()}"

    # First call: Executes action
    res1 = await FailureRecoveryEngine.execute_with_recovery(
        operation=side_effect_action,
        user_id=test_user.id,
        idempotency_key=idemp_key,
    )
    assert res1.success is True
    assert res1.data["counter"] == 1
    assert action_counter == 1

    # Second call with same idempotency_key: Must return cached result without re-executing
    res2 = await FailureRecoveryEngine.execute_with_recovery(
        operation=side_effect_action,
        user_id=test_user.id,
        idempotency_key=idemp_key,
    )
    assert res2.success is True
    assert res2.data["counter"] == 1
    # Action counter remained 1 (no duplicate action created!)
    assert action_counter == 1
    assert idempotency_manager.get_execution_count(idemp_key) == 2


# ==============================================================================
# Test 11: Bounded Retries with No Infinite Loop (Requirement)
# ==============================================================================
@pytest.mark.asyncio
async def test_bounded_retries_no_infinite_loop(test_user: User):
    """Requirement: Strict bounded retries, no infinite retry loops, and clean safe failure."""
    exec_attempts = 0

    async def permanent_transient_failure():
        nonlocal exec_attempts
        exec_attempts += 1
        raise TimeoutError("External endpoint permanently timing out")

    max_limit = 3
    result = await FailureRecoveryEngine.execute_with_recovery(
        operation=permanent_transient_failure,
        user_id=test_user.id,
        policy=RetryPolicy(max_retries=max_limit, base_delay_seconds=0.01),
    )

    # Must cleanly exit after exactly max_limit retries
    assert result.success is False
    assert result.final_action == "SAFE_FAILURE"
    assert result.attempts_made == max_limit + 1  # 1 initial + 3 retries
    assert exec_attempts == 4
    assert result.state_preserved is True
    assert result.error_code == RecoveryErrorCode.TOOL_EXECUTION_FAILURE
    assert result.user_notification is not None


# ==============================================================================
# Test 12: Acceptance Criteria: Injected Failures Do Not Corrupt Goal State
# ==============================================================================
@pytest.mark.asyncio
async def test_acceptance_criteria_injected_failures_do_not_corrupt_goal_state(
    db_session: AsyncSession, test_user: User
):
    """ACCEPTANCE CRITERIA:

    Injected failures do not corrupt goal state or create duplicate actions.
    """
    # 1. Setup clean initial Goal and Task
    goal = Goal(
        user_id=test_user.id,
        title="Production Deployment",
        objective="Zero-downtime release",
        status=GoalStatus.ACTIVE,
        priority=GoalPriority.HIGH,
    )
    db_session.add(goal)
    await db_session.flush()

    initial_task = Task(
        goal_id=goal.id,
        title="Setup CI/CD",
        status=TaskStatus.COMPLETED,
        version=1,
    )
    db_session.add(initial_task)
    await db_session.commit()

    initial_goal_title = goal.title
    initial_goal_status = goal.status

    # 2. Inject failure during a multi-step mutation
    async def corrupted_mutation():
        # Modify goal state
        goal.title = "CORRUPTED HALF-SAVED TITLE"
        goal.status = GoalStatus.COMPLETED

        # Create phantom task
        phantom_task = Task(
            goal_id=goal.id,
            title="Corrupted Ghost Task",
            status=TaskStatus.PENDING,
            version=1,
        )
        db_session.add(phantom_task)
        await db_session.flush()

        # Injected fatal failure before commit!
        raise OperationalError("Simulated connection abort mid-transaction", {}, None)

    # Execute with recovery and DB transaction rollback
    idemp_key = f"goal_update:{goal.id}:{uuid.uuid4()}"
    recovery_res = await FailureRecoveryEngine.recover_db_transaction(
        db_session=db_session,
        user_id=test_user.id,
        tx_operation=corrupted_mutation,
        idempotency_key=idemp_key,
    )

    # Must safely fail
    assert recovery_res.success is False
    assert recovery_res.final_action == "SAFE_FAILURE"
    assert recovery_res.rollback_applied is True
    assert recovery_res.state_preserved is True

    # 3. Verify Database Goal & Task State remains 100% UNCORRUPTED
    # Refresh goal from database
    await db_session.refresh(goal)
    assert goal.title == initial_goal_title  # Title was NOT corrupted
    assert goal.status == initial_goal_status

    # Verify no phantom tasks exist in the database
    tasks_q = select(Task).where(Task.goal_id == goal.id)
    tasks_res = await db_session.execute(tasks_q)
    persisted_tasks = tasks_res.scalars().all()

    assert len(persisted_tasks) == 1
    assert persisted_tasks[0].title == "Setup CI/CD"
    assert not any(t.title == "Corrupted Ghost Task" for t in persisted_tasks)


# ==============================================================================
# Test 13: REST API Recovery Endpoints
# ==============================================================================
@pytest.mark.asyncio
async def test_api_recovery_endpoints(engine, session_factory):
    """Test GET /api/v1/recovery/notifications, dismiss endpoint, and idempotency check."""
    async with session_factory() as session:
        user = User(
            id=uuid.uuid4(),
            email="api_recovery@example.com",
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
        # Trigger an operation that generates a user notification
        async def failing_op():
            raise TimeoutError("MCP timeout")

        await FailureRecoveryEngine.execute_with_recovery(
            operation=failing_op,
            user_id=user_id,
            policy=RetryPolicy(max_retries=1, base_delay_seconds=0.01),
            operation_name="Remote Analyzer",
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {token}"}

            # 1. GET /api/v1/recovery/notifications
            resp = await client.get("/api/v1/recovery/notifications", headers=headers)
            assert resp.status_code == 200
            notifications = resp.json()
            assert len(notifications) >= 1
            n_id = notifications[0]["notification_id"]
            assert notifications[0]["severity"] == "ERROR"

            # 2. POST /api/v1/recovery/notifications/{id}/dismiss
            dismiss_resp = await client.post(
                f"/api/v1/recovery/notifications/{n_id}/dismiss", headers=headers
            )
            assert dismiss_resp.status_code == 200
            assert dismiss_resp.json()["status"] == "DISMISSED"

            # Verify notification is now dismissed
            resp2 = await client.get("/api/v1/recovery/notifications", headers=headers)
            assert len(resp2.json()) == 0

            # 3. POST /api/v1/recovery/idempotency/check
            idemp_resp = await client.post(
                "/api/v1/recovery/idempotency/check",
                json={"key": "test_key_123"},
                headers=headers,
            )
            assert idemp_resp.status_code == 200
            assert idemp_resp.json()["key"] == "test_key_123"
            assert idemp_resp.json()["is_completed"] is False
    finally:
        app.dependency_overrides.clear()
