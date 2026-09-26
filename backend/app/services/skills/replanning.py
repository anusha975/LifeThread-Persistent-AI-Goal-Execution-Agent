import logging
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.goal import Goal
from app.services.agent_trace.models import EventStatus, ExecutionEventType
from app.services.agent_trace.service import AgentTraceService
from app.services.replanning.engine import AutonomousReplanningEngine
from app.services.replanning.models import ReplanningEvent, ReplanningReason
from app.services.skills.base import AgentSkill
from app.services.skills.evaluation import EvaluationInputs, EvaluationSkill
from app.services.skills.models import FailureBehavior, SkillCategory, SkillExecutionContext

logger = logging.getLogger("lifethread.services.skills.replanning")


class ReplanningInputs(BaseModel):
    """Input contract for ReplanningSkill."""

    model_config = ConfigDict(from_attributes=True)

    goal_id: uuid.UUID = Field(..., description="Target goal ID to replan")
    reason: ReplanningReason = Field(
        default=ReplanningReason.AVAILABLE_TIME_CHANGED,
        description="Trigger reason for replanning",
    )
    description: str = Field(
        default="Replanning triggered via ReplanningSkill",
        description="Human-readable event description",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured event parameters (e.g. daily_available_hours, new_deadline)",
    )
    commit: bool = Field(default=True, description="Commit the new plan version to the database")
    auto_evaluate_after: bool = Field(
        default=True,
        description="Skill composition flag: immediately re-evaluate goal health after replanning",
    )


class ReplanningOutputs(BaseModel):
    """Output contract for ReplanningSkill."""

    model_config = ConfigDict(from_attributes=True)

    goal_id: str
    plan_changed: bool
    new_plan_version: int | None = None
    is_feasible: bool = True
    rescheduled_count: int = 0
    added_count: int = 0
    removed_count: int = 0
    explanation: str
    post_evaluation: dict[str, Any] | None = None
    message: str


class ReplanningSkill(AgentSkill):
    """Reusable skill for autonomously rebalancing task schedules and critical path dependencies."""

    name = "replanning"
    purpose = "Rebalances critical path tasks, schedules, and resource allocations when unexpected timeline, failure, or capacity changes occur."
    category = SkillCategory.REPLANNING
    inputs_model = ReplanningInputs
    outputs_model = ReplanningOutputs
    required_permissions = ["plan:write", "replan:execute"]
    tools = [
        "AutonomousReplanningEngine.process_event",
        "EvaluationSkill",
    ]
    failure_behavior = FailureBehavior.ROLLBACK_AND_NOTIFY

    async def _execute_internal(
        self,
        context: SkillExecutionContext,
        inputs: ReplanningInputs,
    ) -> ReplanningOutputs:
        db = context.db
        user_id = context.user_id
        run_id = context.run_id or ""
        goal_id = inputs.goal_id

        goal = await db.get(Goal, goal_id)
        if not goal or goal.user_id != user_id:
            raise ValueError(f"Goal '{goal_id}' not found for user")

        # 1. Construct replanning event and process through Autonomous Replanning Engine
        event = ReplanningEvent(
            goal_id=goal_id,
            user_id=user_id,
            reason=inputs.reason,
            description=inputs.description,
            details=inputs.details,
        )

        decision = await AutonomousReplanningEngine.process_event(
            db=db,
            event=event,
            commit=inputs.commit,
        )

        resched_count = len(decision.diff.tasks_rescheduled) if decision.diff else 0
        added_count = len(decision.diff.tasks_added) if decision.diff else 0
        removed_count = len(decision.diff.tasks_removed) if decision.diff else 0
        new_v = decision.new_plan_version

        AgentTraceService.record_event(
            run_id=run_id,
            user_id=user_id,
            event_type=ExecutionEventType.TOOL_CALL,
            status=EventStatus.SUCCESS,
            short_explanation=f"Executed 'AutonomousReplanningEngine.process_event': Plan v{new_v} created, {resched_count} tasks shifted.",
            goal_id=goal_id,
            goal_title=goal.title,
            tool_name="AutonomousReplanningEngine.process_event",
            tool_parameters={"reason": inputs.reason.value, "commit": inputs.commit},
        )

        # 2. Skill Composition: If auto_evaluate_after is set, compose EvaluationSkill!
        post_eval_data = None
        if inputs.auto_evaluate_after and inputs.commit:
            logger.info("Composing ReplanningSkill with EvaluationSkill for goal %s", goal_id)
            eval_skill = EvaluationSkill()
            eval_result = await eval_skill.execute(
                context=context,
                inputs=EvaluationInputs(goal_id=goal_id, check_dependencies=True),
            )
            if eval_result.success:
                post_eval_data = eval_result.data

        resp_msg = (
            f"Successfully replanned goal '{goal.title}' (Plan v{new_v or 'unchanged'}): "
            f"{resched_count} task(s) rescheduled, feasibility={decision.is_feasible}."
        )

        return ReplanningOutputs(
            goal_id=str(goal_id),
            plan_changed=decision.replanning_required,
            new_plan_version=new_v,
            is_feasible=decision.is_feasible,
            rescheduled_count=resched_count,
            added_count=added_count,
            removed_count=removed_count,
            explanation=decision.explanation,
            post_evaluation=post_eval_data,
            message=resp_msg,
        )
