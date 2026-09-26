import uuid

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.middleware.security import get_rate_limiter
from app.services.agent_trace.models import (
    CoTSanitizer,
    EventStatus,
    ExecutionEventType,
)
from app.services.agent_trace.service import AgentTraceService
from app.services.orchestrator.models import ChatRequest
from app.services.orchestrator.service import AgentOrchestrator
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    get_rate_limiter().reset()
    yield
    get_rate_limiter().reset()


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
        email=f"trace_system_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashedpass",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"unauth_trace_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashedpass",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_client(test_user: User, session_factory):
    token, _, _ = create_access_token(subject=str(test_user.id))

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def other_auth_client(other_user: User, session_factory):
    token, _, _ = create_access_token(subject=str(other_user.id))

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


# =============================================================================
# 1. CoT Sanitizer & Private Reasoning Protection Tests
# =============================================================================


def test_cot_sanitizer_strips_thinking_tags():
    """Verify raw chain-of-thought XML tags and hidden tokens are thoroughly stripped."""
    raw_text = (
        "<thinking>The user wants to reschedule, but let's check if they have enough capacity. "
        "I will calculate the variance internally.</thinking>"
        "Rescheduled task to Friday to balance your workload."
    )
    sanitized = CoTSanitizer.sanitize_text(raw_text)
    assert "<thinking>" not in sanitized
    assert "</thinking>" not in sanitized
    assert "calculate the variance internally" not in sanitized
    assert "Rescheduled task to Friday" in sanitized


def test_cot_sanitizer_strips_scratchpad_and_internal_tokens():
    """Verify scratchpad, hidden tokens, and private reasoning blocks are stripped."""
    raw_text = (
        "<scratchpad>secret heuristic weights: [0.8, 0.2]</scratchpad>"
        "[private_reasoning]Internal agent monologue[/private_reasoning]"
        "[Chain-of-Thought]Step 1: plan; Step 2: execute[/Chain-of-Thought]"
        "Final action chosen: Deploy service."
    )
    sanitized = CoTSanitizer.sanitize_text(raw_text)
    assert "secret heuristic" not in sanitized
    assert "Internal agent monologue" not in sanitized
    assert "Step 1: plan" not in sanitized
    assert "Final action chosen: Deploy service." in sanitized


def test_cot_sanitizer_removes_private_keys_recursively():
    """Verify dictionary payloads with CoT keys are purged recursively."""
    payload = {
        "status": "success",
        "action": "reschedule_task",
        "rationale": "Deadline moved by user.",
        "cot": "I secretly think the deadline is too tight.",
        "chain_of_thought": {"internal_eval": "risky"},
        "scratchpad": "temporary notes",
        "hidden_thoughts": ["thought1", "thought2"],
        "nested": {
            "safe_key": "safe_value",
            "private_reasoning": "do not expose",
            "deep": {
                "raw_thought": "hidden",
                "clean_metric": 42,
            },
        },
    }
    clean = CoTSanitizer.sanitize_payload(payload)

    assert "cot" not in clean
    assert "chain_of_thought" not in clean
    assert "scratchpad" not in clean
    assert "hidden_thoughts" not in clean
    assert clean["status"] == "success"
    assert clean["action"] == "reschedule_task"
    assert clean["rationale"] == "Deadline moved by user."
    assert clean["nested"]["safe_key"] == "safe_value"
    assert "private_reasoning" not in clean["nested"]
    assert "raw_thought" not in clean["nested"]["deep"]
    assert clean["nested"]["deep"]["clean_metric"] == 42


# =============================================================================
# 2. Complete 10-Stage Trace & Reconstruction Tests
# =============================================================================


@pytest.mark.asyncio
async def test_complete_10_stage_trace_lifecycle(db_session: AsyncSession, test_user: User):
    """Requirement: Create a complete trace covering all 10 stages:
    1. input
    2. selected context
    3. retrieved memories
    4. selected tools
    5. tool calls
    6. tool results
    7. evaluation
    8. state changes
    9. replanning event
    10. final user-facing result
    """
    correlation_id = f"corr-{uuid.uuid4().hex[:12]}"
    goal_id = uuid.uuid4()

    # 1. Input: start run with input_data
    run = AgentTraceService.start_run(
        user_id=test_user.id,
        trigger="CONVERSATION:CHANGE_DEADLINE",
        goal_id=goal_id,
        goal_title="Prepare Product Launch",
        summary="User requested: 'Change the deadline to Friday.'",
        correlation_id=correlation_id,
        input_data={
            "user_utterance": "Change the deadline to Friday.",
            "intent": "CHANGE_DEADLINE",
            "slots": {"raw_date": "Friday"},
            "cot": "<thinking>internal private thoughts</thinking>",
        },
    )

    assert run.trace_id is not None
    assert run.correlation_id == correlation_id
    assert run.status == EventStatus.RUNNING

    # 2. Selected Context
    AgentTraceService.record_selected_context(
        run_id=run.id,
        user_id=test_user.id,
        context={
            "goal_id": str(goal_id),
            "goal_title": "Prepare Product Launch",
            "session_id": correlation_id,
        },
        rationale="Active goal resolved from current session.",
    )

    # 3. Retrieved Memories
    AgentTraceService.record_retrieved_memories(
        run_id=run.id,
        user_id=test_user.id,
        memories=[
            {"id": "mem-1", "content": "Prefers Fridays for deliverables", "category": "Preference", "confidence": 0.95}
        ],
        query="Friday scheduling preferences",
        rationale="Checked user preferences for deadline rescheduling.",
    )

    # 4. Selected Tools
    AgentTraceService.record_selected_tools(
        run_id=run.id,
        user_id=test_user.id,
        tools=["planning_skill", "update_goal_deadline"],
        rationale="Selected planning skill to execute schedule modification.",
    )

    # 5. Tool Call
    AgentTraceService.record_event(
        run_id=run.id,
        user_id=test_user.id,
        event_type=ExecutionEventType.TOOL_CALL,
        status=EventStatus.SUCCESS,
        short_explanation="Invoked deadline update handler.",
        tool_name="update_goal_deadline",
        tool_parameters={"goal_id": str(goal_id), "new_deadline": "2026-10-02T18:00:00Z"},
    )

    # 6. Tool Result
    AgentTraceService.record_event(
        run_id=run.id,
        user_id=test_user.id,
        event_type=ExecutionEventType.TOOL_RESULT,
        status=EventStatus.SUCCESS,
        short_explanation="Database updated deadline successfully.",
        tool_name="update_goal_deadline",
        tool_result={"updated": True, "deadline": "2026-10-02T18:00:00Z"},
    )

    # 7. Evaluation
    AgentTraceService.record_evaluation(
        run_id=run.id,
        user_id=test_user.id,
        evaluation_data={
            "feasibility": True,
            "deadline_risk": "LOW",
            "explanation": "Schedule is feasible under new deadline.",
        },
    )

    # 8. State Changes
    AgentTraceService.record_state_changes(
        run_id=run.id,
        user_id=test_user.id,
        state_changes={"deadline": "2026-10-02T18:00:00Z", "plan_version": 2},
    )

    # 9. Replanning Event
    AgentTraceService.record_replanning_event(
        run_id=run.id,
        user_id=test_user.id,
        replanning_data={
            "reason": "GOAL_DEADLINE_CHANGED",
            "previous_version": 1,
            "new_version": 2,
            "tasks_rescheduled": 3,
        },
    )

    # 10. Final User-Facing Result
    AgentTraceService.record_final_result(
        run_id=run.id,
        user_id=test_user.id,
        final_result={
            "response_text": "Successfully updated deadline for 'Prepare Product Launch' to Friday, Oct 2, 2026.",
            "card_type": "deadline_updated",
            "status": "success",
        },
        rationale="Operation completed successfully without schedule conflicts.",
    )

    AgentTraceService.finish_run(run_id=run.id, user_id=test_user.id, status=EventStatus.SUCCESS)

    # Reconstruct trace
    reconstruction = await AgentTraceService.reconstruct_trace(
        db=db_session,
        trace_id=run.trace_id,
        user_id=test_user.id,
    )

    assert reconstruction is not None
    assert reconstruction.is_reconstructible is True
    assert reconstruction.trace_id == run.trace_id
    assert reconstruction.correlation_id == correlation_id
    assert reconstruction.status == EventStatus.SUCCESS

    # Verify each of the 10 stages
    assert reconstruction.input is not None
    assert reconstruction.input["user_utterance"] == "Change the deadline to Friday."
    assert "cot" not in reconstruction.input  # Sanitized!

    assert reconstruction.selected_context is not None
    assert reconstruction.selected_context["goal_title"] == "Prepare Product Launch"

    assert reconstruction.retrieved_memories is not None
    assert len(reconstruction.retrieved_memories) == 1
    assert reconstruction.retrieved_memories[0]["category"] == "Preference"

    assert reconstruction.selected_tools is not None
    assert "planning_skill" in reconstruction.selected_tools

    assert len(reconstruction.tool_calls) >= 1
    assert reconstruction.tool_calls[0]["tool_name"] == "update_goal_deadline"

    assert len(reconstruction.tool_results) >= 1
    assert reconstruction.tool_results[0]["result"]["updated"] is True

    assert reconstruction.evaluation is not None
    assert reconstruction.evaluation["feasibility"] is True

    assert reconstruction.state_changes is not None
    assert reconstruction.state_changes["plan_version"] == 2

    assert reconstruction.replanning_event is not None
    assert reconstruction.replanning_event["reason"] == "GOAL_DEADLINE_CHANGED"

    assert reconstruction.final_user_facing_result is not None
    assert "Successfully updated deadline" in reconstruction.final_user_facing_result["response_text"]


# =============================================================================
# 3. Conversational Orchestrator Trace Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_conversational_chat_records_trace_and_correlation(
    db_session: AsyncSession,
    test_user: User,
):
    """Verify real conversational commands generate trace_id and correlation_id in ChatResponse."""
    session_id = f"session-conv-{uuid.uuid4().hex[:8]}"

    # Send conversational command to create goal
    request = ChatRequest(
        message="Create a goal: Master Microservices in 45 days",
        session_id=session_id,
    )

    response = await AgentOrchestrator.process_chat(
        db=db_session,
        user_id=test_user.id,
        request=request,
    )

    assert response.trace_id is not None
    assert response.correlation_id == session_id
    assert response.run_id is not None
    assert response.message.trace_id == response.trace_id

    # Reconstruct the run
    reconstructed = await AgentTraceService.reconstruct_trace(
        db=db_session,
        trace_id=response.trace_id,
        user_id=test_user.id,
    )
    assert reconstructed is not None
    assert reconstructed.is_reconstructible is True
    assert reconstructed.input["message"] == "Create a goal: Master Microservices in 45 days"
    assert reconstructed.selected_context["session_id"] == session_id
    assert reconstructed.final_user_facing_result is not None
    assert "Master Microservices" in reconstructed.final_user_facing_result["response_text"]


# =============================================================================
# 4. REST API Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
async def test_list_traces_api(auth_client: AsyncClient, test_user: User):
    """Verify GET /api/v1/agent/traces returns user execution traces with filtering."""
    corr_id = f"corr-api-{uuid.uuid4().hex[:6]}"
    run = AgentTraceService.start_run(
        user_id=test_user.id,
        trigger="TEST_API",
        summary="API trace testing run",
        correlation_id=corr_id,
    )
    AgentTraceService.finish_run(run.id, test_user.id, EventStatus.SUCCESS)

    # 1. List traces without filter
    res = await auth_client.get("/api/v1/agent/traces")
    assert res.status_code == 200
    traces = res.json()
    assert len(traces) >= 1
    found = next((t for t in traces if t["trace_id"] == run.trace_id), None)
    assert found is not None
    assert found["correlation_id"] == corr_id

    # 2. Filter by correlation_id
    res_filter = await auth_client.get(f"/api/v1/agent/traces?correlation_id={corr_id}")
    assert res_filter.status_code == 200
    filtered = res_filter.json()
    assert len(filtered) == 1
    assert filtered[0]["trace_id"] == run.trace_id


@pytest.mark.asyncio
async def test_get_trace_by_id_api(auth_client: AsyncClient, test_user: User):
    """Verify GET /api/v1/agent/traces/{trace_id} returns the specific agent run."""
    run = AgentTraceService.start_run(
        user_id=test_user.id,
        trigger="TEST_SINGLE",
        summary="Single trace fetch test",
    )
    AgentTraceService.finish_run(run.id, test_user.id, EventStatus.SUCCESS)

    res = await auth_client.get(f"/api/v1/agent/traces/{run.trace_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["trace_id"] == run.trace_id
    assert data["summary"] == "Single trace fetch test"


@pytest.mark.asyncio
async def test_reconstruct_trace_api(auth_client: AsyncClient, test_user: User):
    """Verify GET /api/v1/agent/traces/{trace_id}/reconstruct endpoint."""
    run = AgentTraceService.start_run(
        user_id=test_user.id,
        trigger="TEST_RECONSTRUCT",
        summary="Reconstruction endpoint test",
        correlation_id="corr-recon-123",
        input_data={"instruction": "Diagnose bottleneck"},
    )
    AgentTraceService.record_selected_tools(
        run_id=run.id,
        user_id=test_user.id,
        tools=["evaluation_tool"],
        rationale="Diagnosing bottlenecks",
    )
    AgentTraceService.record_final_result(
        run_id=run.id,
        user_id=test_user.id,
        final_result={"bottleneck": "Database indexing"},
    )
    AgentTraceService.finish_run(run.id, test_user.id, EventStatus.SUCCESS)

    res = await auth_client.get(f"/api/v1/agent/traces/{run.trace_id}/reconstruct")
    assert res.status_code == 200
    data = res.json()
    assert data["is_reconstructible"] is True
    assert data["trace_id"] == run.trace_id
    assert data["correlation_id"] == "corr-recon-123"
    assert data["input"]["instruction"] == "Diagnose bottleneck"
    assert "evaluation_tool" in data["selected_tools"]
    assert data["final_user_facing_result"]["bottleneck"] == "Database indexing"


# =============================================================================
# 5. Multi-Tenant Isolation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_trace_multi_tenant_isolation(
    test_user: User,
    other_user: User,
    other_auth_client: AsyncClient,
):
    """Verify User B cannot fetch or reconstruct User A's traces."""
    # User A creates a trace
    run_a = AgentTraceService.start_run(
        user_id=test_user.id,
        trigger="PRIVATE_A",
        summary="User A sensitive run",
        correlation_id="corr-secret-a",
        input_data={"private_data": "secret_user_a"},
    )
    AgentTraceService.finish_run(run_a.id, test_user.id, EventStatus.SUCCESS)

    # User B attempts to access User A's trace
    res = await other_auth_client.get(f"/api/v1/agent/traces/{run_a.trace_id}")
    assert res.status_code == 404

    # User B attempts to reconstruct User A's trace
    res_recon = await other_auth_client.get(f"/api/v1/agent/traces/{run_a.trace_id}/reconstruct")
    assert res_recon.status_code == 404
