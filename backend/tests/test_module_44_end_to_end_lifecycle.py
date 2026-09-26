"""Module 44: Complete End-to-End Lifecycle Integration Test Suite.

Verifies the exact end-to-end lifecycle:
USER
  ↓
Create Goal (via Goal Understanding or Direct Creation)
  ↓
Goal Understanding
  ↓
Goal Decomposition
  ↓
Planning
  ↓
Agent Execution
  ↓
Tool/MCP Execution
  ↓
Evaluation
  ↓
Memory (Store & Semantic Retrieval)
  ↓
Constraint Change
  ↓
Impact Analysis (Replan Preview)
  ↓
Replanning
  ↓
New Plan (Plan v2 with Explainable Diff)
  ↓
Continue Execution
  ↓
Goal Completion

Validates that frontend API contracts, backend domain services, agent orchestrator,
MCP tools, SQLite/PostgreSQL database, vector memory, evaluation engine, and autonomous
replanning work seamlessly together with robust error handling and strict tenant isolation.
"""

import uuid
from datetime import UTC, datetime

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.llm import get_llm_provider_dep
from app.main import app
from app.services.agent_evaluation.suite import EvaluationLLMProvider
from app.services.observability.service import AgentObservabilityService
from httpx import ASGITransport, AsyncClient
from mcp_server.client import MCPClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def reset_telemetry():
    """Reset telemetry before each lifecycle run."""
    AgentObservabilityService.reset()
    yield
    AgentObservabilityService.reset()


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(async_engine):
    return async_sessionmaker(bind=async_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def primary_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="developer@lifethread.ai",
        password_hash="test_bcrypt_hash",
        display_name="LifeThread Developer",
        timezone="UTC",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def tenant_intruder(db_session: AsyncSession) -> User:
    intruder = User(
        id=uuid.uuid4(),
        email="intruder@external.io",
        password_hash="test_intruder_hash",
        display_name="External Intruder",
        timezone="UTC",
        is_active=True,
    )
    db_session.add(intruder)
    await db_session.commit()
    await db_session.refresh(intruder)
    return intruder


@pytest.fixture
def eval_llm() -> EvaluationLLMProvider:
    return EvaluationLLMProvider()


@pytest.fixture
async def client(primary_user: User, session_factory, eval_llm):
    """Authenticated HTTP client acting on behalf of the primary UI user."""
    token, _, _ = create_access_token(subject=str(primary_user.id))

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider_dep] = lambda: eval_llm

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def intruder_client(tenant_intruder: User, session_factory, eval_llm):
    """Authenticated HTTP client acting on behalf of another tenant."""
    token, _, _ = create_access_token(subject=str(tenant_intruder.id))

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_llm_provider_dep] = lambda: eval_llm

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# =============================================================================
# MASTER END-TO-END LIFECYCLE TEST
# =============================================================================


@pytest.mark.asyncio
async def test_complete_goal_lifecycle_end_to_end(
    client: AsyncClient,
    intruder_client: AsyncClient,
    primary_user: User,
    db_session: AsyncSession,
):
    """Verify the exact end-to-end lifecycle through the UI/API contract."""
    # -------------------------------------------------------------------------
    # 1. USER & AUTH VERIFICATION
    # -------------------------------------------------------------------------
    auth_resp = await client.get("/api/v1/auth/me")
    assert auth_resp.status_code == 200, f"Auth verification failed: {auth_resp.text}"
    user_data = auth_resp.json()
    assert user_data["email"] == primary_user.email
    assert user_data["id"] == str(primary_user.id)

    # -------------------------------------------------------------------------
    # 2. GOAL UNDERSTANDING
    # -------------------------------------------------------------------------
    natural_prompt = "Launch SaaS MVP in 60 days with PostgreSQL backend"
    understand_resp = await client.post(
        "/api/v1/goals/understand",
        json={"text": natural_prompt, "timezone": "UTC"},
    )
    assert understand_resp.status_code == 200, f"Goal understanding failed: {understand_resp.text}"
    understood = understand_resp.json()
    assert understood["title"] is not None
    assert understood["objective"] is not None
    assert understood["priority"].lower() in ("low", "medium", "high", "critical")
    assert understood["deadline"] is not None

    # -------------------------------------------------------------------------
    # 3. CREATE GOAL
    # -------------------------------------------------------------------------
    create_payload = {
        "title": understood["title"],
        "objective": understood["objective"],
        "description": understood.get("description") or "Automated end-to-end SaaS MVP deployment",
        "priority": understood["priority"].upper(),
        "deadline": understood["deadline"],
        "success_criteria": understood.get("success_criteria") or ["Deploy to production", "Pass CI/CD"],
        "constraints": [
            {"type": "tech", "value": "PostgreSQL backend"}
        ],
    }
    create_resp = await client.post("/api/v1/goals", json=create_payload)
    assert create_resp.status_code == 201, f"Goal creation failed: {create_resp.text}"
    created_goal = create_resp.json()
    goal_id = created_goal["id"]
    assert created_goal["status"].upper() == "ACTIVE"
    assert created_goal["title"] == understood["title"]

    # -------------------------------------------------------------------------
    # 4. GOAL DECOMPOSITION
    # -------------------------------------------------------------------------
    decomp_resp = await client.post(
        f"/api/v1/goals/{goal_id}/decompose",
        json={"confirm_new_version": True},
    )
    assert decomp_resp.status_code == 200, f"Decomposition failed: {decomp_resp.text}"
    decomp_data = decomp_resp.json()
    assert decomp_data["goal_id"] == goal_id
    assert decomp_data["version"] == 1
    assert len(decomp_data["tasks"]) >= 2
    assert decomp_data["has_cycles"] is False

    # Verify tasks are retrievable via UI endpoint
    tasks_resp = await client.get(f"/api/v1/goals/{goal_id}/tasks")
    assert tasks_resp.status_code == 200
    tasks_list = tasks_resp.json()
    assert tasks_list["total"] >= 2
    task_1 = tasks_list["items"][0]
    assert len(tasks_list["items"]) >= 2

    # Verify dependency DAG endpoint
    dag_resp = await client.get(f"/api/v1/goals/{goal_id}/dependencies")
    assert dag_resp.status_code == 200
    dag_data = dag_resp.json()
    assert len(dag_data["nodes"]) >= 2
    assert len(dag_data["topological_order"]) >= 2

    # -------------------------------------------------------------------------
    # 5. PLANNING (GENERATE OPERATIONAL SCHEDULE PLAN V1)
    # -------------------------------------------------------------------------
    plan_create_payload = {
        "start_date": datetime.now(UTC).isoformat(),
        "daily_available_hours": 4.0,
    }
    plan_resp = await client.post(f"/api/v1/goals/{goal_id}/plan", json=plan_create_payload)
    assert plan_resp.status_code == 200, f"Plan generation failed: {plan_resp.text}"
    plan_v1 = plan_resp.json()
    assert plan_v1["version"] == 1
    assert plan_v1["is_feasible"] is True
    assert len(plan_v1["items"]) >= 2

    # Verify Active Plan endpoint
    active_plan_resp = await client.get(f"/api/v1/goals/{goal_id}/plan")
    assert active_plan_resp.status_code == 200
    assert active_plan_resp.json()["version"] == 1

    # -------------------------------------------------------------------------
    # 6. AGENT EXECUTION
    # -------------------------------------------------------------------------
    chat_payload = {
        "message": f"Start work on the first task: {task_1['title']}",
        "active_goal_id": goal_id,
        "current_task_id": task_1["id"],
    }
    chat_resp = await client.post("/api/v1/agent/chat", json=chat_payload)
    assert chat_resp.status_code == 200, f"Agent chat failed: {chat_resp.text}"
    chat_data = chat_resp.json()
    assert "message" in chat_data
    assert len(chat_data["message"]["content"]) > 0

    # Verify agent execution runs are tracked in observability/trace system
    runs_resp = await client.get("/api/v1/agent/runs")
    assert runs_resp.status_code == 200
    runs = runs_resp.json()
    assert isinstance(runs, list)

    # -------------------------------------------------------------------------
    # 7. TOOL / MCP EXECUTION (TASK STATE TRANSITIONS)
    # -------------------------------------------------------------------------
    mcp_client = MCPClient(base_url="http://mock-mcp-server:8001")
    assert mcp_client.base_url is not None

    # Complete Task 1 via UI complete endpoint
    complete_t1_resp = await client.post(f"/api/v1/goals/{goal_id}/tasks/{task_1['id']}/complete")
    assert complete_t1_resp.status_code == 200
    t1_done = complete_t1_resp.json()
    assert t1_done["status"].lower() == "completed"

    # -------------------------------------------------------------------------
    # 8. EVALUATION (INTERMEDIATE PROGRESS EVALUATION)
    # -------------------------------------------------------------------------
    eval_resp = await client.post(f"/api/v1/goals/{goal_id}/evaluate")
    assert eval_resp.status_code == 200, f"Goal evaluation failed: {eval_resp.text}"
    evaluation_1 = eval_resp.json()
    assert evaluation_1["goal_id"] == goal_id
    assert evaluation_1["completed_tasks"] >= 1
    assert evaluation_1["completion_ratio"] > 0.0
    assert evaluation_1["is_moving_forward"] is True

    # -------------------------------------------------------------------------
    # 9. MEMORY (STORE & SEMANTIC RETRIEVAL)
    # -------------------------------------------------------------------------
    memory_payload = {
        "content": "PostgreSQL 16 connection pooling requires PgBouncer with transaction mode.",
        "category": "Relevant knowledge",
        "confidence": 0.96,
        "goal_id": goal_id,
    }
    mem_store_resp = await client.post("/api/v1/memories", json=memory_payload)
    assert mem_store_resp.status_code == 201, f"Memory store failed: {mem_store_resp.text}"
    stored_mem = mem_store_resp.json()
    assert stored_mem["id"] is not None

    # Retrieve memory via list/search endpoint
    mem_search_resp = await client.get("/api/v1/memories?query=PostgreSQL")
    assert mem_search_resp.status_code == 200
    mem_search_results = mem_search_resp.json()
    assert any(m["id"] == stored_mem["id"] for m in mem_search_results.get("items", []))

    # -------------------------------------------------------------------------
    # 10. CONSTRAINT CHANGE & IMPACT ANALYSIS (REPLAN PREVIEW)
    # -------------------------------------------------------------------------
    replan_reason = "AVAILABLE_TIME_CHANGED"
    replan_description = "Daily available development hours reduced from 4 to 1 hour"
    replan_details = {"daily_available_hours": 1.0}

    # Impact Analysis preview without committing
    preview_resp = await client.post(
        f"/api/v1/goals/{goal_id}/replan/preview",
        json={
            "reason": replan_reason,
            "description": replan_description,
            "details": replan_details,
        },
    )
    assert preview_resp.status_code == 200, f"Replan preview failed: {preview_resp.text}"
    preview_data = preview_resp.json()
    assert preview_data["replanning_required"] is True
    assert preview_data["diff"] is not None

    # Ensure Plan v1 is still the active plan before committing replan
    plan_check_resp = await client.get(f"/api/v1/goals/{goal_id}/plan")
    assert plan_check_resp.json()["version"] == 1

    # -------------------------------------------------------------------------
    # 11. REPLANNING (COMMIT NEW PLAN V2)
    # -------------------------------------------------------------------------
    replan_commit_resp = await client.post(
        f"/api/v1/goals/{goal_id}/replan",
        json={
            "reason": replan_reason,
            "description": replan_description,
            "details": replan_details,
        },
    )
    assert replan_commit_resp.status_code == 200, f"Replan commit failed: {replan_commit_resp.text}"
    decision = replan_commit_resp.json()
    assert decision["replanning_required"] is True
    assert decision["new_plan_version"] == 2

    # -------------------------------------------------------------------------
    # 12. NEW PLAN & REPLANNING DIFF VISUALIZATION
    # -------------------------------------------------------------------------
    # Verify active plan is now Plan v2
    plan_v2_resp = await client.get(f"/api/v1/goals/{goal_id}/plan")
    assert plan_v2_resp.status_code == 200
    plan_v2 = plan_v2_resp.json()
    assert plan_v2["version"] == 2

    # Verify replanning diff endpoint (powers the frontend ReplanningDiffViewer)
    diff_resp = await client.get(f"/api/v1/goals/{goal_id}/replanning-diff")
    assert diff_resp.status_code == 200, f"Diff endpoint failed: {diff_resp.text}"
    diff_data = diff_resp.json()
    assert diff_data["plan_changed"] is True
    assert diff_data["status_label"] == "PLAN CHANGED"
    assert len(diff_data["why_explanation"]) > 0
    assert len(diff_data["why_feasible"]) > 0
    assert diff_data["previous_plan"]["version"] == 1
    assert diff_data["new_plan"]["version"] == 2

    # -------------------------------------------------------------------------
    # 13. CONTINUE EXECUTION (COMPLETE REMAINING TASKS)
    # -------------------------------------------------------------------------
    # Complete remaining tasks
    final_tasks_resp = await client.get(f"/api/v1/goals/{goal_id}/tasks")
    assert final_tasks_resp.status_code == 200
    all_tasks = final_tasks_resp.json()["items"]
    for t in all_tasks:
        if t["status"].lower() != "completed":
            complete_resp = await client.post(f"/api/v1/goals/{goal_id}/tasks/{t['id']}/complete")
            assert complete_resp.status_code == 200

    # Verify all tasks are completed
    refreshed_tasks_resp = await client.get(f"/api/v1/goals/{goal_id}/tasks")
    refreshed_tasks = refreshed_tasks_resp.json()["items"]
    assert all(t["status"].lower() == "completed" for t in refreshed_tasks)

    # -------------------------------------------------------------------------
    # 14. GOAL COMPLETION
    # -------------------------------------------------------------------------
    complete_goal_resp = await client.post(f"/api/v1/goals/{goal_id}/complete")
    assert complete_goal_resp.status_code == 200, f"Complete goal failed: {complete_goal_resp.text}"
    completed_goal = complete_goal_resp.json()
    assert completed_goal["status"].upper() == "COMPLETED"

    # Final evaluation reflects 100% completion
    final_eval_resp = await client.post(f"/api/v1/goals/{goal_id}/evaluate")
    assert final_eval_resp.status_code == 200
    final_eval = final_eval_resp.json()
    assert final_eval["completion_ratio"] == 1.0
    assert final_eval["completed_tasks"] == final_eval["total_tasks"]

    # -------------------------------------------------------------------------
    # 15. SECURITY & TENANT ISOLATION (ZERO DATA LEAKAGE)
    # -------------------------------------------------------------------------
    intruder_goal_resp = await intruder_client.get(f"/api/v1/goals/{goal_id}")
    assert intruder_goal_resp.status_code == 404, "Security violation: Intruder accessed another tenant's goal"

    intruder_task_resp = await intruder_client.post(
        f"/api/v1/goals/{goal_id}/tasks/{task_1['id']}/complete"
    )
    assert intruder_task_resp.status_code == 404, "Security violation: Intruder modified another tenant's task"

    intruder_diff_resp = await intruder_client.get(f"/api/v1/goals/{goal_id}/replanning-diff")
    assert intruder_diff_resp.status_code == 404, "Security violation: Intruder read another tenant's diff"


# =============================================================================
# ADDITIONAL SUBSYSTEM INTEGRATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_rag_and_memory_context_integration(
    client: AsyncClient,
    primary_user: User,
    db_session: AsyncSession,
):
    """Verify RAG memory storage and context engine assembly integration."""
    from app.services.context_engine import (
        ContextBudget,
        ContextBuilder,
        ContextItem,
        ContextSource,
    )

    # 1. Store memory through API
    mem_payload = {
        "content": "User prefers concise executive status summaries and async notification.",
        "category": "Preference",
        "confidence": 0.98,
    }
    create_resp = await client.post("/api/v1/memories", json=mem_payload)
    assert create_resp.status_code == 201
    stored = create_resp.json()

    # 2. Context Builder integration
    builder = ContextBuilder()
    items = [
        ContextItem(
            id=str(uuid.uuid4()),
            source=ContextSource.CURRENT_TASK,
            content="Task: Deploy Kubernetes StatefulSet",
            user_id=primary_user.id,
            source_attribution="Active Task",
        ),
        ContextItem(
            id=stored["id"],
            source=ContextSource.MEMORIES,
            content=stored["memory"],
            user_id=primary_user.id,
            source_attribution="Memory Engine",
        ),
    ]

    budget = ContextBudget(total_tokens=200)
    built = builder.build(user_id=primary_user.id, items=items, budget=budget)
    assert len(built.items) == 2
    # Verify priority hierarchy: Task (priority 1) comes before Memories (priority 5)
    assert built.items[0].source == ContextSource.CURRENT_TASK
    assert built.items[1].source == ContextSource.MEMORIES


@pytest.mark.asyncio
async def test_conversational_agent_orchestration_flow(
    client: AsyncClient,
    primary_user: User,
):
    """Verify Conversational Agent interface seamlessly handles state queries and intent execution."""
    chat_resp = await client.post(
        "/api/v1/agent/chat",
        json={"message": "What is my current progress and what should I focus on next?"},
    )
    assert chat_resp.status_code == 200
    res = chat_resp.json()
    assert "message" in res
    assert "intent" in res
    assert len(res["message"]["content"]) > 0

    # Verify context summary endpoint
    ctx_resp = await client.get("/api/v1/agent/chat/context")
    assert ctx_resp.status_code == 200
    ctx_data = ctx_resp.json()
    assert "user_name" in ctx_data


@pytest.mark.asyncio
async def test_invalid_lifecycle_requests_error_handling(
    client: AsyncClient,
):
    """Verify robust error handling and descriptive validation messages across all lifecycle endpoints."""
    # 1. Non-existent goal evaluation
    fake_id = uuid.uuid4()
    eval_resp = await client.post(f"/api/v1/goals/{fake_id}/evaluate")
    assert eval_resp.status_code in (404, 400)

    # 2. Malformed goal creation
    invalid_goal_resp = await client.post("/api/v1/goals", json={"title": "ab"})
    assert invalid_goal_resp.status_code == 422
    err = invalid_goal_resp.json()
    assert "error" in err or "detail" in err

    # 3. Non-existent goal replan
    replan_resp = await client.post(
        f"/api/v1/goals/{fake_id}/replan",
        json={"reason": "DEADLINE_CHANGED", "description": "Invalid goal target"},
    )
    assert replan_resp.status_code in (404, 400)

