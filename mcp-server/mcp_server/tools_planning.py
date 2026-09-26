import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.exceptions import LifeThreadException
from app.db.models.goal import GoalPriority
from app.db.models.plan import Plan, PlanStatus
from app.db.models.task import GoalDecomposition, Task, TaskDependency, TaskStatus
from app.schemas.plan import PlanCreateRequest
from app.services.critical_path import CriticalPathService
from app.services.dependency_graph import DependencyGraphService
from app.services.goal import GoalService
from app.services.planning import PlanningService
from fastapi import HTTPException
from lifethread_agent.tools import ToolPermissionLevel, ToolRegistry
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("lifethread.mcp.tools.planning")


# ============================================================================
# PRECISE SCHEMAS
# ============================================================================


class PlanItemToolOutput(BaseModel):
    """Output representation of a single scheduled plan item."""

    id: uuid.UUID | None = None
    task_id: uuid.UUID
    task_title: str | None = None
    scheduled_start: datetime
    scheduled_end: datetime
    priority: GoalPriority
    rationale: str

    model_config = ConfigDict(from_attributes=True)


class PlanToolOutput(BaseModel):
    """Structured output representation of a committed execution plan."""

    id: uuid.UUID
    goal_id: uuid.UUID
    version: int
    status: str
    generated_at: datetime
    reason: str | None = None
    is_feasible: bool
    deadline_risk: float
    risk_level: str
    schedule_utilization: float
    total_duration_minutes: int
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    items: list[PlanItemToolOutput] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ReplanPreviewToolOutput(BaseModel):
    """Simulated schedule outcome returned by replan_preview without database commit."""

    goal_id: uuid.UUID
    is_committed: bool = Field(
        default=False,
        description="Always False to guarantee changes remain uncommitted until approved",
    )
    proposed_is_feasible: bool
    proposed_risk_level: str
    proposed_deadline_risk: float
    proposed_total_duration_minutes: int
    proposed_scheduled_start: datetime | None = None
    proposed_scheduled_end: datetime | None = None
    schedule_delta_days: float | None = Field(
        default=None,
        description="Difference in days compared to current active plan (positive = takes longer)",
    )
    risk_delta: str | None = Field(
        default=None,
        description="Shift in risk level, e.g. 'MEDIUM -> LOW' or 'Unchanged'",
    )
    proposed_items: list[PlanItemToolOutput] = Field(default_factory=list)
    summary: str = Field(..., description="Summary explanation of the replan preview")


class TaskToolOutput(BaseModel):
    """Structured output representation of a task."""

    id: uuid.UUID
    goal_id: uuid.UUID
    milestone_id: uuid.UUID | None = None
    version: int
    title: str
    description: str | None = None
    status: TaskStatus
    priority: GoalPriority
    estimated_minutes: int
    due_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class GeneratePlanToolInput(BaseModel):
    """Input payload to generate and commit a new versioned plan."""

    goal_id: uuid.UUID = Field(..., description="UUID of the target goal")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated goal owner")
    daily_available_hours: float = Field(
        default=4.0,
        ge=0.5,
        le=24.0,
        description="Daily user working capacity in hours",
    )
    start_date: datetime | None = Field(
        default=None, description="Optional start datetime for the schedule"
    )
    reason: str | None = Field(
        default=None, description="Optional reason justifying plan generation"
    )
    workdays_only: bool = Field(
        default=True, description="Whether to schedule only on Monday-Friday"
    )
    daily_start_hour: int = Field(
        default=9, ge=0, le=23, description="Starting hour of each workday (0-23)"
    )


class GetPlanToolInput(BaseModel):
    """Input payload to retrieve an active or historical plan."""

    goal_id: uuid.UUID = Field(..., description="UUID of the target goal")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated goal owner")
    version: int | None = Field(
        default=None,
        description="Optional plan version number (retrieves active plan if omitted)",
    )


class ReplanPreviewToolInput(BaseModel):
    """Input payload to simulate a replan scenario without committing changes."""

    goal_id: uuid.UUID = Field(..., description="UUID of the target goal")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated goal owner")
    daily_available_hours: float = Field(
        default=4.0,
        ge=0.5,
        le=24.0,
        description="Proposed daily working capacity in hours",
    )
    start_date: datetime | None = Field(default=None, description="Proposed start datetime")
    workdays_only: bool = Field(default=True, description="Whether to schedule only on workdays")
    daily_start_hour: int = Field(default=9, ge=0, le=23, description="Daily start hour")
    hypothetical_task_estimates: dict[str, int] = Field(
        default_factory=dict,
        description="Map of task_id string to proposed estimated minutes",
    )
    hypothetical_task_priorities: dict[str, GoalPriority] = Field(
        default_factory=dict,
        description="Map of task_id string to proposed GoalPriority",
    )
    reason: str | None = Field(
        default=None, description="Context or scenario description for preview"
    )


class UpdateTaskToolInput(BaseModel):
    """Input payload to update an existing task."""

    task_id: uuid.UUID = Field(..., description="UUID of the task to update")
    goal_id: uuid.UUID = Field(..., description="UUID of the parent goal")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated goal owner")
    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    estimated_minutes: int | None = Field(
        default=None, ge=1, description="Effort estimate in minutes"
    )
    due_at: datetime | None = None
    status: TaskStatus | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if len(stripped) < 2:
                raise ValueError("Task title must be at least 2 non-whitespace characters")
            return stripped
        return v


class PrioritizeTaskToolInput(BaseModel):
    """Input payload to adjust task priority."""

    task_id: uuid.UUID = Field(..., description="UUID of the task")
    goal_id: uuid.UUID = Field(..., description="UUID of the parent goal")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated goal owner")
    priority: GoalPriority = Field(
        ..., description="New priority to assign: CRITICAL, HIGH, MEDIUM, LOW"
    )
    reason: str | None = Field(
        default=None, description="Optional rationale for priority adjustment"
    )


# ============================================================================
# DATABASE SESSION RESOLVER
# ============================================================================


@asynccontextmanager
async def _resolve_db_session(context: dict[str, Any] | None) -> AsyncGenerator[AsyncSession, None]:
    if context and "db" in context:
        yield context["db"]
    else:
        from app.db.session import transaction_context

        async with transaction_context() as session:
            yield session


# ============================================================================
# TOOL REGISTRATION
# ============================================================================


def register_planning_mcp_tools(registry: ToolRegistry) -> None:
    """Register the 5 Planning Engine MCP tools into the registry."""

    # 1. GENERATE PLAN
    @registry.tool(
        name="generate_plan",
        description="Generate and commit a new versioned plan allocating tasks across user available time.",
        input_schema=GeneratePlanToolInput,
        output_schema=PlanToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def generate_plan(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        daily_available_hours: float = 4.0,
        start_date: datetime | None = None,
        reason: str | None = None,
        workdays_only: bool = True,
        daily_start_hour: int = 9,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"MCP Tool [generate_plan] invoked for goal [{goal_id}] by user [{user_id}]")
        plan_req = PlanCreateRequest(
            daily_available_hours=daily_available_hours,
            start_date=start_date,
            reason=reason,
            workdays_only=workdays_only,
            daily_start_hour=daily_start_hour,
        )

        async with _resolve_db_session(context) as session:
            try:
                plan_resp = await PlanningService.generate_plan(
                    db=session,
                    goal_id=goal_id,
                    user_id=user_id,
                    request=plan_req,
                )
            except LifeThreadException as lte:
                logger.warning(f"MCP Tool [generate_plan] error: {lte.message}")
                raise ValueError(lte.message) from lte
            except HTTPException as he:
                raise ValueError(he.detail) from he

            logger.info(
                f"MCP Tool [generate_plan] committed plan version [{plan_resp.version}] for goal [{goal_id}]"
            )
            return plan_resp.model_dump(mode="json")

    # 2. GET PLAN
    @registry.tool(
        name="get_plan",
        description="Retrieve an active plan or specific historical plan version for a goal.",
        input_schema=GetPlanToolInput,
        output_schema=PlanToolOutput,
        permission_level=ToolPermissionLevel.READ_ONLY,
    )
    async def get_plan(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        version: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            f"MCP Tool [get_plan] query for goal [{goal_id}] (version: {version}) by user [{user_id}]"
        )
        async with _resolve_db_session(context) as session:
            try:
                if version is not None:
                    plan_resp = await PlanningService.get_plan_by_version(
                        db=session,
                        goal_id=goal_id,
                        user_id=user_id,
                        version=version,
                    )
                else:
                    plan_resp = await PlanningService.get_active_plan(
                        db=session,
                        goal_id=goal_id,
                        user_id=user_id,
                    )
            except (LifeThreadException, HTTPException) as exc:
                msg = getattr(exc, "message", getattr(exc, "detail", str(exc)))
                logger.warning(f"MCP Tool [get_plan] failed: {msg}")
                raise ValueError(f"Plan not found or access denied: {msg}") from exc

            return plan_resp.model_dump(mode="json")

    # 3. REPLAN PREVIEW (Dry run / preview - NO COMMIT)
    @registry.tool(
        name="replan_preview",
        description="Simulate a proposed schedule change and return projected outcome WITHOUT committing it to the database.",
        input_schema=ReplanPreviewToolInput,
        output_schema=ReplanPreviewToolOutput,
        permission_level=ToolPermissionLevel.READ_ONLY,
    )
    async def replan_preview(
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        daily_available_hours: float = 4.0,
        start_date: datetime | None = None,
        workdays_only: bool = True,
        daily_start_hour: int = 9,
        hypothetical_task_estimates: dict[str, int] | None = None,
        hypothetical_task_priorities: dict[str, GoalPriority] | None = None,
        reason: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            f"MCP Tool [replan_preview] simulating schedule for goal [{goal_id}] by user [{user_id}]"
        )
        task_estimates = hypothetical_task_estimates or {}
        task_priorities = hypothetical_task_priorities or {}

        async with _resolve_db_session(context) as session:
            try:
                goal = await GoalService.get_goal_by_id(
                    db=session, goal_id=goal_id, user_id=user_id
                )
            except HTTPException as exc:
                raise ValueError(
                    f"Goal '{goal_id}' not found or access denied: {exc.detail}"
                ) from exc

            # Fetch active decomposition version
            decomp_q = (
                select(GoalDecomposition)
                .where(GoalDecomposition.goal_id == goal_id, GoalDecomposition.is_active.is_(True))
                .order_by(GoalDecomposition.version.desc())
            )
            decomp_res = await session.execute(decomp_q)
            active_decomp = decomp_res.scalars().first()
            target_version = active_decomp.version if active_decomp else 1

            tasks_q = select(Task).where(Task.goal_id == goal_id, Task.version == target_version)
            tasks_res = await session.execute(tasks_q)
            tasks = list(tasks_res.scalars().all())

            if not tasks:
                raise ValueError("Cannot simulate replan: Goal has no tasks decomposed.")

            # Create ephemeral mock copies for simulation
            task_map: dict[uuid.UUID, Task] = {}
            for t in tasks:
                # Copy values
                tid_str = str(t.id)
                new_est = task_estimates.get(tid_str, t.estimated_minutes)
                new_prio = task_priorities.get(tid_str, t.priority)

                mock_task = Task(
                    id=t.id,
                    goal_id=t.goal_id,
                    milestone_id=t.milestone_id,
                    version=t.version,
                    title=t.title,
                    description=t.description,
                    status=t.status,
                    priority=new_prio,
                    estimated_minutes=new_est,
                    due_at=t.due_at,
                )
                task_map[t.id] = mock_task

            # Get dependencies
            task_ids = list(task_map.keys())
            deps_q = select(TaskDependency).where(TaskDependency.task_id.in_(task_ids))
            deps_res = await session.execute(deps_q)
            dependencies = deps_res.scalars().all()
            edges = [(d.depends_on_task_id, d.task_id) for d in dependencies]

            # Run deterministic calculations
            topological_order = DependencyGraphService.topological_sort(task_ids, edges)
            critical_path_ids, _, _ = CriticalPathService.calculate_critical_path(
                tasks=list(task_map.values()),
                dependencies=edges,
                topological_order=topological_order,
            )
            critical_path_set = set(critical_path_ids)

            user_tz = ZoneInfo("UTC")
            sim_start = start_date or datetime.now(UTC)
            if sim_start.tzinfo is None:
                sim_start = sim_start.replace(tzinfo=UTC)

            scheduled_items, plan_end, total_capacity_minutes = (
                PlanningService._schedule_tasks_calendar(
                    tasks=list(task_map.values()),
                    task_map=task_map,
                    edges=edges,
                    topological_order=topological_order,
                    critical_path_set=critical_path_set,
                    plan_start=sim_start,
                    user_tz=user_tz,
                    daily_available_hours=daily_available_hours,
                    workdays_only=workdays_only,
                    daily_start_hour=daily_start_hour,
                )
            )

            total_task_minutes = sum(t.estimated_minutes for t in task_map.values())

            goal_deadline = goal.deadline
            if goal_deadline is not None and goal_deadline.tzinfo is None:
                goal_deadline = goal_deadline.replace(tzinfo=UTC)

            deadline_risk, risk_level = PlanningService._calculate_deadline_risk(
                plan_start=sim_start,
                plan_end=plan_end,
                deadline=goal_deadline,
            )

            is_feasible = True
            if goal_deadline is not None and plan_end > goal_deadline:
                is_feasible = False

            # Check if active plan exists to compute deltas
            active_plan_q = select(Plan).where(
                Plan.goal_id == goal_id, Plan.status == PlanStatus.ACTIVE
            )
            active_res = await session.execute(active_plan_q)
            active_plan = active_res.scalars().first()

            schedule_delta_days = None
            risk_delta = None
            if active_plan and active_plan.scheduled_end:
                active_end = (
                    active_plan.scheduled_end
                    if active_plan.scheduled_end.tzinfo
                    else active_plan.scheduled_end.replace(tzinfo=UTC)
                )
                delta_sec = (plan_end - active_end).total_seconds()
                schedule_delta_days = round(delta_sec / 86400.0, 2)
                risk_delta = f"{active_plan.risk_level} -> {risk_level}"

            # Format items
            proposed_items = [
                PlanItemToolOutput(
                    id=None,
                    task_id=it["task_id"],
                    task_title=task_map[it["task_id"]].title,
                    scheduled_start=it["start"],
                    scheduled_end=it["end"],
                    priority=it["priority"],
                    rationale=it["rationale"],
                )
                for it in scheduled_items
            ]

            summary = (
                f"Preview: {len(proposed_items)} tasks projected across {total_task_minutes} mins. "
                f"Feasible: {is_feasible}. Risk: {risk_level} ({deadline_risk}). "
                f"Uncommitted dry run."
            )

            preview_output = ReplanPreviewToolOutput(
                goal_id=goal_id,
                is_committed=False,
                proposed_is_feasible=is_feasible,
                proposed_risk_level=risk_level,
                proposed_deadline_risk=deadline_risk,
                proposed_total_duration_minutes=total_task_minutes,
                proposed_scheduled_start=sim_start,
                proposed_scheduled_end=plan_end,
                schedule_delta_days=schedule_delta_days,
                risk_delta=risk_delta,
                proposed_items=proposed_items,
                summary=summary,
            )

            return preview_output.model_dump(mode="json")

    # 4. UPDATE TASK
    @registry.tool(
        name="update_task",
        description="Update fields on an existing decomposed task (title, description, estimate, status).",
        input_schema=UpdateTaskToolInput,
        output_schema=TaskToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def update_task(
        task_id: uuid.UUID,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str | None = None,
        description: str | None = None,
        estimated_minutes: int | None = None,
        due_at: datetime | None = None,
        status: TaskStatus | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(f"MCP Tool [update_task] updating task [{task_id}] for goal [{goal_id}]")
        async with _resolve_db_session(context) as session:
            try:
                await GoalService.get_goal_by_id(db=session, goal_id=goal_id, user_id=user_id)
            except HTTPException as exc:
                raise ValueError(
                    f"Goal '{goal_id}' not found or access denied: {exc.detail}"
                ) from exc

            task_q = select(Task).where(Task.id == task_id, Task.goal_id == goal_id)
            task_res = await session.execute(task_q)
            task = task_res.scalar_one_or_none()

            if not task:
                raise ValueError(f"Task '{task_id}' not found for goal '{goal_id}'")

            if title is not None:
                task.title = title
            if description is not None:
                task.description = description
            if estimated_minutes is not None:
                task.estimated_minutes = estimated_minutes
            if due_at is not None:
                task.due_at = due_at
            if status is not None:
                task.status = status
                if status == TaskStatus.COMPLETED and task.completed_at is None:
                    task.completed_at = datetime.now(UTC)

            await session.flush()
            await session.refresh(task)

            logger.info(f"MCP Tool [update_task] successfully updated task [{task_id}]")
            return TaskToolOutput.model_validate(task).model_dump(mode="json")

    # 5. PRIORITIZE TASK
    @registry.tool(
        name="prioritize_task",
        description="Adjust priority level on an existing task (CRITICAL, HIGH, MEDIUM, LOW).",
        input_schema=PrioritizeTaskToolInput,
        output_schema=TaskToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def prioritize_task(
        task_id: uuid.UUID,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        priority: GoalPriority,
        reason: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            f"MCP Tool [prioritize_task] setting priority {priority.value} on task [{task_id}] (reason: {reason})"
        )
        async with _resolve_db_session(context) as session:
            try:
                await GoalService.get_goal_by_id(db=session, goal_id=goal_id, user_id=user_id)
            except HTTPException as exc:
                raise ValueError(
                    f"Goal '{goal_id}' not found or access denied: {exc.detail}"
                ) from exc

            task_q = select(Task).where(Task.id == task_id, Task.goal_id == goal_id)
            task_res = await session.execute(task_q)
            task = task_res.scalar_one_or_none()

            if not task:
                raise ValueError(f"Task '{task_id}' not found for goal '{goal_id}'")

            task.priority = priority
            await session.flush()
            await session.refresh(task)

            logger.info(
                f"MCP Tool [prioritize_task] updated task [{task_id}] to priority {priority.value}"
            )
            return TaskToolOutput.model_validate(task).model_dump(mode="json")
