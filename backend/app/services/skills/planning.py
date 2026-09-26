import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.goal import Goal
from app.db.models.task import GoalDecomposition, Task
from app.schemas.decomposition import DecompositionRequest
from app.schemas.plan import PlanCreateRequest
from app.services.agent_trace.models import EventStatus, ExecutionEventType
from app.services.agent_trace.service import AgentTraceService
from app.services.decomposition import DecompositionService
from app.services.llm.mock import MockLLMProvider
from app.services.planning import PlanningService
from app.services.skills.base import AgentSkill
from app.services.skills.models import FailureBehavior, SkillCategory, SkillExecutionContext

logger = logging.getLogger("lifethread.services.skills.planning")


class PlanningInputs(BaseModel):
    """Input contract for PlanningSkill."""

    model_config = ConfigDict(from_attributes=True)

    goal_id: uuid.UUID = Field(..., description="Target goal ID to decompose and schedule")
    start_date: datetime | None = Field(default=None, description="Plan start date")
    daily_capacity_hours: float = Field(default=4.0, ge=0.5, le=16.0, description="Available daily hours")
    decompose_if_needed: bool = Field(default=True, description="Autonomously decompose goal if no active decomposition exists")


class PlanningOutputs(BaseModel):
    """Output contract for PlanningSkill."""

    model_config = ConfigDict(from_attributes=True)

    goal_id: str
    plan_version: int
    milestones_count: int
    tasks_count: int
    first_task_id: str | None = None
    first_task_title: str | None = None
    total_duration_days: int
    message: str


class PlanningSkill(AgentSkill):
    """Reusable skill for decomposing goals and generating executable time-bounded plans."""

    name = "planning"
    purpose = "Decomposes goals into milestones and tasks, resolves dependency graphs, and generates time-bounded execution plans."
    category = SkillCategory.PLANNING
    inputs_model = PlanningInputs
    outputs_model = PlanningOutputs
    required_permissions = ["plan:generate", "decomposition:write"]
    tools = [
        "DecompositionService.decompose_goal",
        "PlanningService.generate_plan",
    ]
    failure_behavior = FailureBehavior.FALLBACK_DEFAULT

    async def _execute_internal(
        self,
        context: SkillExecutionContext,
        inputs: PlanningInputs,
    ) -> PlanningOutputs:
        db = context.db
        user_id = context.user_id
        run_id = context.run_id or ""
        goal_id = inputs.goal_id

        # 1. Verify goal exists and is active
        goal = await db.get(Goal, goal_id)
        if not goal or goal.user_id != user_id:
            raise ValueError(f"Goal '{goal_id}' not found for user")

        now = inputs.start_date or datetime.now(UTC)

        # 2. Check if decomposition exists; if not and decompose_if_needed, decompose
        decomp_q = (
            select(GoalDecomposition)
            .where(GoalDecomposition.goal_id == goal_id, GoalDecomposition.is_active.is_(True))
            .order_by(GoalDecomposition.version.desc())
        )
        decomp_res = await db.execute(decomp_q)
        active_decomp = decomp_res.scalars().first()

        milestones_count = 0
        tasks_count = 0

        if not active_decomp and inputs.decompose_if_needed:
            # Prepare mock/fallback provider if LLM unavailable
            settings = get_settings()
            mock_llm = None
            if not settings.OPENAI_API_KEY or "CHANGEME" in settings.OPENAI_API_KEY:
                mock_json = json.dumps({
                    "milestones": [
                        {"title": f"Phase 1: {goal.title} Foundations", "description": "Core concepts and initial setup", "order_index": 0},
                        {"title": f"Phase 2: {goal.title} Execution", "description": "Implementation and delivery", "order_index": 1},
                    ],
                    "tasks": [
                        {"temp_id": "T1", "milestone_index": 0, "title": f"Study {goal.title} requirements", "description": "Review specs", "priority": "HIGH", "estimated_minutes": 60},
                        {"temp_id": "T2", "milestone_index": 0, "title": f"Implement core foundation for {goal.title}", "description": "Build baseline", "priority": "HIGH", "estimated_minutes": 120},
                        {"temp_id": "T3", "milestone_index": 1, "title": f"Complete implementation of {goal.title}", "description": "Finalize deliverable", "priority": "MEDIUM", "estimated_minutes": 180},
                    ],
                    "dependencies": [
                        {"task_temp_id": "T2", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"},
                        {"task_temp_id": "T3", "depends_on_temp_id": "T2", "dependency_type": "BLOCKS"},
                    ],
                })
                mock_llm = MockLLMProvider(default_response=mock_json)

            decomp_result = await DecompositionService.decompose_goal(
                db=db,
                goal_id=goal_id,
                user_id=user_id,
                request=DecompositionRequest(),
                llm_provider=mock_llm,
            )
            milestones_count = len(decomp_result.milestones)
            tasks_count = len(decomp_result.tasks)

            AgentTraceService.record_event(
                run_id=run_id,
                user_id=user_id,
                event_type=ExecutionEventType.TOOL_CALL,
                status=EventStatus.SUCCESS,
                short_explanation=f"Executed 'DecompositionService.decompose_goal': {tasks_count} tasks generated.",
                goal_id=goal_id,
                goal_title=goal.title,
                tool_name="DecompositionService.decompose_goal",
            )
        elif active_decomp:
            tasks_q = select(Task).where(Task.goal_id == goal_id, Task.version == active_decomp.version)
            tasks_res = await db.execute(tasks_q)
            tasks = list(tasks_res.scalars().all())
            tasks_count = len(tasks)
            milestones_count = len(goal.milestones) if goal.milestones else 2

        # 3. Generate Plan
        plan_resp = await PlanningService.generate_plan(
            db=db,
            goal_id=goal_id,
            user_id=user_id,
            request=PlanCreateRequest(start_date=now),
        )

        first_task = plan_resp.items[0] if plan_resp.items else None
        total_duration = max(1, (plan_resp.items[-1].scheduled_end.date() - now.date()).days) if plan_resp.items else 1

        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.TOOL_CALL,
            status=EventStatus.SUCCESS,
            short_explanation=f"Executed 'PlanningService.generate_plan': Plan v{plan_resp.version} created.",
            goal_id=goal_id,
            goal_title=goal.title,
            tool_name="PlanningService.generate_plan",
        )

        return PlanningOutputs(
            goal_id=str(goal_id),
            plan_version=plan_resp.version,
            milestones_count=milestones_count,
            tasks_count=len(plan_resp.items),
            first_task_id=str(first_task.task_id) if first_task else None,
            first_task_title=first_task.task_title if first_task else None,
            total_duration_days=total_duration,
            message=f"Generated Plan v{plan_resp.version} for '{goal.title}' with {len(plan_resp.items)} scheduled tasks.",
        )

    async def _fallback_default(
        self,
        context: SkillExecutionContext,
        inputs: PlanningInputs,
        exc: Exception,
    ) -> dict[str, Any]:
        """Structured fallback baseline schedule when planning encounter errors."""
        logger.warning("PlanningSkill fallback activated for goal %s: %s", inputs.goal_id, exc)
        return {
            "goal_id": str(inputs.goal_id),
            "plan_version": 1,
            "milestones_count": 1,
            "tasks_count": 1,
            "first_task_id": None,
            "first_task_title": "Initial Baseline Task",
            "total_duration_days": 14,
            "message": "Fallback default linear schedule applied due to planning constraint.",
            "fallback": True,
        }
