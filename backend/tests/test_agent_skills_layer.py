import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.services.replanning.models import ReplanningReason
from app.services.skills.evaluation import EvaluationInputs, EvaluationSkill
from app.services.skills.goal_management import GoalManagementInputs, GoalManagementSkill
from app.services.skills.memory import MemoryInputs, MemorySkill
from app.services.skills.models import (
    FailureBehavior,
    SkillCategory,
    SkillExecutionContext,
    SkillPipelineRequest,
    SkillPipelineStep,
)
from app.services.skills.planning import PlanningInputs, PlanningSkill
from app.services.skills.registry import SkillRegistry
from app.services.skills.replanning import ReplanningInputs, ReplanningSkill
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


@pytest_asyncio.fixture
async def test_user(async_db: AsyncSession) -> User:
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="skills_test_user@example.com",
        display_name="Skills Engineer",
        password_hash="pw",
        is_active=True,
    )
    async_db.add(user)
    await async_db.commit()
    return user


# =============================================================================
# 1. Skill Discovery & Metadata Introspection
# =============================================================================


def test_skill_discovery_and_metadata():
    """Verify all 5 canonical skills are discovered and define required contracts."""
    SkillRegistry.initialize_default_skills()
    skills = SkillRegistry.list_skills()
    names = [s.name for s in skills]

    assert "goal_management" in names
    assert "planning" in names
    assert "memory" in names
    assert "evaluation" in names
    assert "replanning" in names

    meta_list = SkillRegistry.list_skill_metadata()
    assert len(meta_list) == 5

    for meta in meta_list:
        assert meta.name
        assert meta.purpose
        assert meta.category in [c.value for c in SkillCategory]
        assert len(meta.required_permissions) > 0
        assert len(meta.tools) > 0
        assert meta.failure_behavior in [f.value for f in FailureBehavior]
        assert "properties" in meta.inputs_schema
        assert "properties" in meta.outputs_schema


# =============================================================================
# 2. Skill Selection
# =============================================================================


def test_skill_selection_from_user_requests():
    """Verify appropriate skill is selected based on user requests."""
    # Goal Management
    skill_gm = SkillRegistry.select_skill("Create a goal to learn Rust")
    assert skill_gm is not None
    assert skill_gm.name == "goal_management"

    skill_dl = SkillRegistry.select_skill("Change the deadline to Friday.")
    assert skill_dl is not None
    assert skill_dl.name == "goal_management"

    # Planning
    skill_plan = SkillRegistry.select_skill("Decompose my goal and generate plan")
    assert skill_plan is not None
    assert skill_plan.name == "planning"

    # Memory
    skill_mem = SkillRegistry.select_skill("Remember that I struggle with SQL joins.")
    assert skill_mem is not None
    assert skill_mem.name == "memory"

    skill_mem_q = SkillRegistry.select_skill("What do you remember?")
    assert skill_mem_q is not None
    assert skill_mem_q.name == "memory"

    # Evaluation
    skill_eval = SkillRegistry.select_skill("What should I do next?")
    assert skill_eval is not None
    assert skill_eval.name == "evaluation"

    skill_block = SkillRegistry.select_skill("What is blocking my goal?")
    assert skill_block is not None
    assert skill_block.name == "evaluation"

    # Replanning
    skill_replan = SkillRegistry.select_skill("I only have one hour today to work on my plan.")
    assert skill_replan is not None
    assert skill_replan.name == "replanning"


# =============================================================================
# 3. Independent Skill Execution & Validation
# =============================================================================


@pytest.mark.asyncio
async def test_goal_management_skill_execution(async_db: AsyncSession, test_user: User):
    """Test GoalManagementSkill independently: create, get, update_deadline, list."""
    skill = GoalManagementSkill()
    context = SkillExecutionContext(
        user_id=test_user.id,
        db=async_db,
        user_permissions={"*"},
    )

    # 1. Create Goal
    create_inputs = GoalManagementInputs(
        action="create",
        title="Skill Architecture Design",
        objective="Implement clean agent skills layer",
        priority=GoalPriority.HIGH,
        deadline=datetime.now(UTC) + timedelta(days=14),
    )
    res_create = await skill.execute(context=context, inputs=create_inputs)
    assert res_create.success is True
    assert res_create.data["title"] == "Skill Architecture Design"
    goal_id = uuid.UUID(res_create.data["goal_id"])

    # 2. Get Goal
    res_get = await skill.execute(
        context=context,
        inputs=GoalManagementInputs(action="get", goal_id=goal_id),
    )
    assert res_get.success is True
    assert res_get.data["goal_id"] == str(goal_id)

    # 3. Update Deadline
    new_dl = datetime.now(UTC) + timedelta(days=21)
    res_dl = await skill.execute(
        context=context,
        inputs=GoalManagementInputs(action="update_deadline", goal_id=goal_id, deadline=new_dl),
    )
    assert res_dl.success is True
    assert res_dl.data["deadline"] == new_dl.isoformat()

    # 4. List Goals
    res_list = await skill.execute(
        context=context,
        inputs=GoalManagementInputs(action="list"),
    )
    assert res_list.success is True
    assert res_list.data["goals_count"] >= 1


@pytest.mark.asyncio
async def test_planning_skill_execution(async_db: AsyncSession, test_user: User):
    """Test PlanningSkill independently: decomposition and Plan v1 creation."""
    goal = Goal(
        id=uuid.uuid4(),
        user_id=test_user.id,
        title="Distributed Consensus",
        objective="Raft implementation in Rust",
        description="Study distributed systems",
        priority=GoalPriority.HIGH,
        status=GoalStatus.ACTIVE,
    )
    async_db.add(goal)
    await async_db.commit()

    skill = PlanningSkill()
    context = SkillExecutionContext(
        user_id=test_user.id,
        db=async_db,
        goal_id=goal.id,
        user_permissions={"*"},
    )

    inputs = PlanningInputs(goal_id=goal.id, decompose_if_needed=True, daily_capacity_hours=4.0)
    res = await skill.execute(context=context, inputs=inputs)

    assert res.success is True
    assert res.data["plan_version"] >= 1
    assert res.data["tasks_count"] > 0
    assert res.data["milestones_count"] > 0


@pytest.mark.asyncio
async def test_memory_skill_execution(async_db: AsyncSession, test_user: User):
    """Test MemorySkill independently: store, retrieve, delete."""
    skill = MemorySkill()
    context = SkillExecutionContext(
        user_id=test_user.id,
        db=async_db,
        user_permissions={"*"},
    )

    # 1. Store
    res_store = await skill.execute(
        context=context,
        inputs=MemoryInputs(
            action="store",
            content="Prefers working in the early morning",
            category="Preference",
        ),
    )
    assert res_store.success is True
    assert res_store.data["category"] == "Preference"
    memory_id = uuid.UUID(res_store.data["memory_id"])

    # 2. Retrieve
    res_ret = await skill.execute(
        context=context,
        inputs=MemoryInputs(action="retrieve", query="morning"),
    )
    assert res_ret.success is True
    assert res_ret.data["count"] >= 1
    assert any("morning" in m["content"] for m in res_ret.data["memories"])

    # 3. Delete
    res_del = await skill.execute(
        context=context,
        inputs=MemoryInputs(action="delete", memory_id=memory_id),
    )
    assert res_del.success is True
    assert res_del.data["memory_id"] == str(memory_id)


@pytest.mark.asyncio
async def test_evaluation_skill_execution(async_db: AsyncSession, test_user: User):
    """Test EvaluationSkill independently: progress, blockers, critical path."""
    goal = Goal(
        id=uuid.uuid4(),
        user_id=test_user.id,
        title="Evaluation Goal",
        objective="Assess health",
        description="Goal for evaluation skill testing",
        priority=GoalPriority.MEDIUM,
        status=GoalStatus.ACTIVE,
    )
    async_db.add(goal)
    await async_db.commit()

    skill = EvaluationSkill()
    context = SkillExecutionContext(
        user_id=test_user.id,
        db=async_db,
        goal_id=goal.id,
        user_permissions={"*"},
    )

    inputs = EvaluationInputs(goal_id=goal.id, check_dependencies=True)
    res = await skill.execute(context=context, inputs=inputs)

    assert res.success is True
    assert res.data["goal_id"] == str(goal.id)
    assert "progress_percentage" in res.data
    assert "deadline_risk" in res.data
    assert "recommended_action" in res.data


@pytest.mark.asyncio
async def test_replanning_skill_and_composition(async_db: AsyncSession, test_user: User):
    """Test ReplanningSkill and verify composability with EvaluationSkill."""
    goal = Goal(
        id=uuid.uuid4(),
        user_id=test_user.id,
        title="Replanning Test Goal",
        objective="Test dynamic schedule shift",
        description="Replanning test",
        priority=GoalPriority.HIGH,
        status=GoalStatus.ACTIVE,
    )
    async_db.add(goal)
    await async_db.commit()

    # Pre-plan goal
    plan_skill = PlanningSkill()
    ctx = SkillExecutionContext(user_id=test_user.id, db=async_db, goal_id=goal.id, user_permissions={"*"})
    await plan_skill.execute(context=ctx, inputs=PlanningInputs(goal_id=goal.id))

    # Execute ReplanningSkill with auto_evaluate_after=True
    replan_skill = ReplanningSkill()
    inputs = ReplanningInputs(
        goal_id=goal.id,
        reason=ReplanningReason.AVAILABLE_TIME_CHANGED,
        description="User reduced capacity to 1 hour",
        details={"daily_available_hours": 1.0},
        commit=True,
        auto_evaluate_after=True,  # Composes EvaluationSkill!
    )
    res = await replan_skill.execute(context=ctx, inputs=inputs)

    assert res.success is True
    assert res.data["plan_changed"] is True
    assert res.data["new_plan_version"] >= 2
    # Composed evaluation output is populated
    assert res.data["post_evaluation"] is not None
    assert "progress_percentage" in res.data["post_evaluation"]


# =============================================================================
# 4. Permission Enforcement & Validation
# =============================================================================


@pytest.mark.asyncio
async def test_skill_permission_enforcement(async_db: AsyncSession, test_user: User):
    """Verify skill halts execution with permission failure when scope is missing."""
    skill = GoalManagementSkill()
    # Context with insufficient permissions (only memory:read)
    restricted_context = SkillExecutionContext(
        user_id=test_user.id,
        db=async_db,
        user_permissions={"memory:read"},  # Missing goal:write
    )

    inputs = GoalManagementInputs(action="create", title="Forbidden Goal")
    res = await skill.execute(context=restricted_context, inputs=inputs)

    assert res.success is False
    assert "Missing required permissions" in (res.error or "")


# =============================================================================
# 5. Composable Skill Pipeline
# =============================================================================


@pytest.mark.asyncio
async def test_composable_skill_pipeline_execution(async_db: AsyncSession, test_user: User):
    """Test composable pipeline chaining: GoalManagement -> Planning -> Evaluation."""
    context = SkillExecutionContext(
        user_id=test_user.id,
        db=async_db,
        user_permissions={"*"},
    )

    # Pipeline:
    # 1. Create Goal
    # 2. Plan Goal
    # 3. Evaluate Goal
    req = SkillPipelineRequest(
        steps=[
            SkillPipelineStep(
                skill_name="goal_management",
                inputs={"action": "create", "title": "Pipeline Goal", "objective": "Pipeline testing"},
            ),
            SkillPipelineStep(
                skill_name="planning",
                inputs={"decompose_if_needed": True, "daily_capacity_hours": 3.0},
                pass_previous_output_key="goal_id",  # Pipes goal_id from step 1!
            ),
            SkillPipelineStep(
                skill_name="evaluation",
                inputs={"check_dependencies": True},
                pass_previous_output_key="goal_id",  # Pipes goal_id from step 2!
            ),
        ]
    )

    pipeline_res = await SkillRegistry.execute_pipeline(request=req, context=context)

    assert pipeline_res.success is True
    assert pipeline_res.total_steps == 3
    assert pipeline_res.completed_steps == 3
    assert len(pipeline_res.step_results) == 3
    assert pipeline_res.step_results[0].skill_name == "goal_management"
    assert pipeline_res.step_results[1].skill_name == "planning"
    assert pipeline_res.step_results[2].skill_name == "evaluation"


# =============================================================================
# 6. REST API Endpoints Verification
# =============================================================================


@pytest.mark.asyncio
async def test_api_list_skills_and_specs(client: AsyncClient, test_user: User):
    """Test GET /api/v1/agent/skills and GET /api/v1/agent/skills/{name}."""
    token, _, _ = create_access_token(subject=str(test_user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # 1. List skills
    resp = await client.get("/api/v1/agent/skills", headers=headers)
    assert resp.status_code == 200
    skills_meta = resp.json()
    assert len(skills_meta) == 5
    names = [s["name"] for s in skills_meta]
    assert "goal_management" in names
    assert "replanning" in names

    # 2. Get skill spec
    resp_spec = await client.get("/api/v1/agent/skills/goal_management", headers=headers)
    assert resp_spec.status_code == 200
    spec = resp_spec.json()
    assert spec["name"] == "goal_management"
    assert "required_permissions" in spec
    assert "tools" in spec
    assert "inputs_schema" in spec


@pytest.mark.asyncio
async def test_api_execute_skill_endpoint(client: AsyncClient, test_user: User):
    """Test POST /api/v1/agent/skills/{name}/execute."""
    token, _, _ = create_access_token(subject=str(test_user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Execute goal_management create
    payload = {
        "action": "create",
        "title": "API Created Goal via Skill",
        "objective": "Testing API execution",
        "priority": "HIGH",
    }
    resp = await client.post("/api/v1/agent/skills/goal_management/execute", json=payload, headers=headers)
    assert resp.status_code == 200
    result = resp.json()
    assert result["success"] is True
    assert result["skill_name"] == "goal_management"
    assert result["data"]["title"] == "API Created Goal via Skill"
