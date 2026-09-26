import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.goal import GoalPriority, GoalStatus
from app.schemas.goal import GoalCreate
from app.services.agent_trace.models import EventStatus, ExecutionEventType
from app.services.agent_trace.service import AgentTraceService
from app.services.goal import GoalService
from app.services.skills.base import AgentSkill
from app.services.skills.models import FailureBehavior, SkillCategory, SkillExecutionContext


class GoalManagementInputs(BaseModel):
    """Input contract for GoalManagementSkill."""

    model_config = ConfigDict(from_attributes=True)

    action: Literal["create", "get", "list", "update_deadline", "update_priority", "switch_goal"] = Field(
        ..., description="Goal management action to perform"
    )
    goal_id: uuid.UUID | None = Field(default=None, description="Target goal ID")
    title: str | None = Field(default=None, description="Goal title for create or switch")
    objective: str | None = Field(default=None, description="Goal objective statement")
    description: str | None = Field(default=None, description="Goal description")
    deadline: datetime | None = Field(default=None, description="Target completion deadline")
    priority: GoalPriority = Field(default=GoalPriority.HIGH, description="Goal priority level")
    status_filter: GoalStatus | None = Field(default=None, description="Status filter when listing goals")


class GoalManagementOutputs(BaseModel):
    """Output contract for GoalManagementSkill."""

    model_config = ConfigDict(from_attributes=True)

    action: str
    goal_id: str | None = None
    title: str | None = None
    priority: str | None = None
    status: str | None = None
    deadline: str | None = None
    goals_count: int = 0
    goals: list[dict[str, Any]] = Field(default_factory=list)
    message: str


class GoalManagementSkill(AgentSkill):
    """Reusable skill for creating, retrieving, listing, and updating user goals."""

    name = "goal_management"
    purpose = "Manages the lifecycle of user goals, including creation, status inspection, deadline updates, and priority rebalancing."
    category = SkillCategory.GOAL_MANAGEMENT
    inputs_model = GoalManagementInputs
    outputs_model = GoalManagementOutputs
    required_permissions = ["goal:read", "goal:write"]
    tools = [
        "GoalService.create_goal",
        "GoalService.get_goal_by_id",
        "GoalService.list_goals",
        "GoalService.update_goal",
    ]
    failure_behavior = FailureBehavior.FAIL_FAST

    async def _execute_internal(
        self,
        context: SkillExecutionContext,
        inputs: GoalManagementInputs,
    ) -> GoalManagementOutputs:
        db = context.db
        user_id = context.user_id
        run_id = context.run_id or ""

        if inputs.action == "create":
            title = inputs.title or "New Goal"
            objective = inputs.objective or f"Complete {title}"
            deadline = inputs.deadline or (datetime.now(UTC) + timedelta(days=30))
            create_in = GoalCreate(
                title=title,
                objective=objective,
                description=inputs.description or "Created via GoalManagementSkill.",
                priority=inputs.priority,
                deadline=deadline,
            )
            goal = await GoalService.create_goal(db=db, user_id=user_id, goal_in=create_in)
            context.goal_id = goal.id

            AgentTraceService.record_event(
                run_id=run_id,
                user_id=user_id,
                event_type=ExecutionEventType.TOOL_CALL,
                status=EventStatus.SUCCESS,
                short_explanation=f"Executed Tool 'GoalService.create_goal' for '{goal.title}'.",
                goal_id=goal.id,
                goal_title=goal.title,
                tool_name="GoalService.create_goal",
                tool_parameters={"title": goal.title, "priority": goal.priority.value},
            )

            return GoalManagementOutputs(
                action="create",
                goal_id=str(goal.id),
                title=goal.title,
                priority=goal.priority.value,
                status=goal.status.value,
                deadline=goal.deadline.isoformat() if goal.deadline else None,
                message=f"Created goal '{goal.title}' successfully.",
            )

        elif inputs.action == "get":
            target_id = inputs.goal_id or context.goal_id
            if not target_id:
                raise ValueError("goal_id required for 'get' action")
            goal = await GoalService.get_goal_by_id(db=db, goal_id=target_id, user_id=user_id)
            if not goal:
                raise ValueError(f"Goal '{target_id}' not found for user")

            return GoalManagementOutputs(
                action="get",
                goal_id=str(goal.id),
                title=goal.title,
                priority=goal.priority.value,
                status=goal.status.value,
                deadline=goal.deadline.isoformat() if goal.deadline else None,
                message=f"Retrieved goal '{goal.title}'.",
            )

        elif inputs.action == "list":
            goals, total = await GoalService.list_goals(
                db=db, user_id=user_id, status_filter=inputs.status_filter
            )
            goal_list = [
                {
                    "id": str(g.id),
                    "title": g.title,
                    "priority": g.priority.value,
                    "status": g.status.value,
                    "deadline": g.deadline.isoformat() if g.deadline else None,
                }
                for g in goals
            ]
            return GoalManagementOutputs(
                action="list",
                goals_count=total,
                goals=goal_list,
                message=f"Retrieved {len(goals)} goals.",
            )

        elif inputs.action == "update_deadline":
            target_id = inputs.goal_id or context.goal_id
            if not target_id:
                raise ValueError("goal_id required for 'update_deadline' action")
            if not inputs.deadline:
                raise ValueError("deadline required for 'update_deadline' action")

            goal = await GoalService.get_goal_by_id(db=db, goal_id=target_id, user_id=user_id)
            if not goal:
                raise ValueError(f"Goal '{target_id}' not found")

            old_dl = goal.deadline
            goal.deadline = inputs.deadline
            await db.flush()

            AgentTraceService.record_event(
                run_id=run_id,
                user_id=user_id,
                event_type=ExecutionEventType.TOOL_CALL,
                status=EventStatus.SUCCESS,
                short_explanation=f"Updated deadline for '{goal.title}' to {inputs.deadline.strftime('%b %d, %Y')}.",
                goal_id=goal.id,
                goal_title=goal.title,
                tool_name="GoalService.update_goal",
                tool_parameters={"goal_id": str(goal.id), "deadline": inputs.deadline.isoformat()},
            )

            return GoalManagementOutputs(
                action="update_deadline",
                goal_id=str(goal.id),
                title=goal.title,
                priority=goal.priority.value,
                status=goal.status.value,
                deadline=inputs.deadline.isoformat(),
                message=f"Updated deadline for '{goal.title}' from {old_dl.strftime('%b %d, %Y') if old_dl else 'None'} to {inputs.deadline.strftime('%b %d, %Y')}.",
            )

        elif inputs.action == "update_priority":
            target_id = inputs.goal_id or context.goal_id
            if not target_id:
                raise ValueError("goal_id required for 'update_priority' action")

            goal = await GoalService.get_goal_by_id(db=db, goal_id=target_id, user_id=user_id)
            if not goal:
                raise ValueError(f"Goal '{target_id}' not found")

            goal.priority = inputs.priority
            await db.flush()

            return GoalManagementOutputs(
                action="update_priority",
                goal_id=str(goal.id),
                title=goal.title,
                priority=goal.priority.value,
                status=goal.status.value,
                deadline=goal.deadline.isoformat() if goal.deadline else None,
                message=f"Updated priority for '{goal.title}' to {inputs.priority.value}.",
            )

        elif inputs.action == "switch_goal":
            # Search by title or goal_id
            goals, _ = await GoalService.list_goals(db=db, user_id=user_id, status_filter=GoalStatus.ACTIVE)
            matched = None
            if inputs.goal_id:
                matched = next((g for g in goals if g.id == inputs.goal_id), None)
            elif inputs.title:
                matched = next((g for g in goals if inputs.title.lower() in g.title.lower()), None)

            if not matched:
                raise ValueError(f"Active goal matching '{inputs.title or inputs.goal_id}' not found")

            context.goal_id = matched.id
            return GoalManagementOutputs(
                action="switch_goal",
                goal_id=str(matched.id),
                title=matched.title,
                priority=matched.priority.value,
                status=matched.status.value,
                deadline=matched.deadline.isoformat() if matched.deadline else None,
                message=f"Switched focus to goal '{matched.title}'.",
            )

        raise ValueError(f"Unsupported goal action: {inputs.action}")
