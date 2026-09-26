import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.goal import Goal
from app.db.models.task import Task, TaskStatus
from app.services.agent_trace.models import EventStatus, ExecutionEventType
from app.services.agent_trace.service import AgentTraceService
from app.services.evaluation import EvaluationService
from app.services.skills.base import AgentSkill
from app.services.skills.models import FailureBehavior, SkillCategory, SkillExecutionContext


class EvaluationInputs(BaseModel):
    """Input contract for EvaluationSkill."""

    model_config = ConfigDict(from_attributes=True)

    goal_id: uuid.UUID = Field(..., description="Target goal ID to evaluate")
    check_dependencies: bool = Field(default=True, description="Perform full dependency blocker diagnostics")


class EvaluationOutputs(BaseModel):
    """Output contract for EvaluationSkill."""

    model_config = ConfigDict(from_attributes=True)

    goal_id: str
    goal_title: str
    progress_percentage: float
    deadline_risk: str
    is_moving_forward: bool
    blockers_count: int
    blockers: list[dict[str, str]] = Field(default_factory=list)
    next_action_task_id: str | None = None
    next_action_title: str | None = None
    recommended_action: str
    message: str


class EvaluationSkill(AgentSkill):
    """Reusable skill for evaluating goal progress, diagnosing blockers, and discovering next critical path action."""

    name = "evaluation"
    purpose = "Evaluates goal execution progress, detects dependency blockers, calculates deadline risk, and identifies the next critical-path action."
    category = SkillCategory.EVALUATION
    inputs_model = EvaluationInputs
    outputs_model = EvaluationOutputs
    required_permissions = ["evaluation:read"]
    tools = [
        "EvaluationService.evaluate_progress",
        "EvaluationService.diagnose_blockers",
    ]
    failure_behavior = FailureBehavior.GRACEFUL_DEGRADATION

    async def _execute_internal(
        self,
        context: SkillExecutionContext,
        inputs: EvaluationInputs,
    ) -> EvaluationOutputs:
        db = context.db
        user_id = context.user_id
        run_id = context.run_id or ""
        goal_id = inputs.goal_id

        goal = await db.get(Goal, goal_id)
        if not goal or goal.user_id != user_id:
            raise ValueError(f"Goal '{goal_id}' not found for user")

        # 1. Run real evaluation
        progress_eval = await EvaluationService.evaluate_progress(
            db=db,
            goal_id=goal_id,
            user_id=user_id,
        )

        # 2. Blockers and next action diagnosis
        tasks_q = (
            select(Task)
            .where(Task.goal_id == goal_id)
            .options(selectinload(Task.outgoing_dependencies))
        )
        tasks_res = await db.execute(tasks_q)
        all_tasks = list(tasks_res.scalars().all())
        task_map = {t.id: t for t in all_tasks}

        blockers: list[dict[str, str]] = []
        unblocked_candidates: list[Task] = []

        if inputs.check_dependencies:
            for t in all_tasks:
                if t.status in [TaskStatus.COMPLETED, TaskStatus.CANCELLED]:
                    continue
                prereqs_done = True
                for dep in t.outgoing_dependencies:
                    prereq = task_map.get(dep.depends_on_task_id)
                    if prereq and prereq.status != TaskStatus.COMPLETED:
                        prereqs_done = False
                        blockers.append({
                            "task_title": t.title,
                            "blocked_by": prereq.title,
                            "prereq_status": prereq.status.value,
                        })
                if prereqs_done:
                    unblocked_candidates.append(t)

        # Select next action
        chosen_task = None
        if unblocked_candidates:
            unblocked_candidates.sort(key=lambda x: (x.priority.value, -x.estimated_minutes))
            chosen_task = unblocked_candidates[0]

        progress_pct = round(progress_eval.goal_progress * 100.0, 1)
        is_moving_forward = (
            progress_eval.completed_tasks > 0
            or progress_eval.in_progress_tasks > 0
            or progress_eval.blocked_tasks == 0
        )

        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.EVALUATION,
            status=EventStatus.SUCCESS,
            short_explanation=f"Evaluated goal '{goal.title}': Progress={progress_pct:.1f}%, Risk={progress_eval.deadline_risk}, Blockers={len(blockers)}.",
            goal_id=goal_id,
            goal_title=goal.title,
            metadata={
                "progress_percentage": progress_pct,
                "deadline_risk": progress_eval.deadline_risk,
                "blockers_count": len(blockers),
            },
        )

        return EvaluationOutputs(
            goal_id=str(goal.id),
            goal_title=goal.title,
            progress_percentage=progress_pct,
            deadline_risk=progress_eval.deadline_risk,
            is_moving_forward=is_moving_forward,
            blockers_count=len(blockers),
            blockers=blockers,
            next_action_task_id=str(chosen_task.id) if chosen_task else None,
            next_action_title=chosen_task.title if chosen_task else None,
            recommended_action=progress_eval.recommended_action,
            message=f"Goal '{goal.title}' is {progress_pct:.1f}% complete with {progress_eval.deadline_risk.upper()} deadline risk.",
        )

    async def _graceful_degrade(
        self,
        context: SkillExecutionContext,
        inputs: EvaluationInputs,
        exc: Exception,
    ) -> dict[str, Any]:
        """Degrade gracefully to baseline evaluation heuristic."""
        return {
            "goal_id": str(inputs.goal_id),
            "goal_title": "Goal Evaluation",
            "progress_percentage": 0.0,
            "deadline_risk": "moderate",
            "is_moving_forward": True,
            "blockers_count": 0,
            "blockers": [],
            "next_action_task_id": None,
            "next_action_title": None,
            "recommended_action": f"Evaluation service degraded: {str(exc)}",
            "message": "Evaluation completed with graceful degradation fallback.",
            "degraded": True,
        }
