import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import LifeThreadException
from app.db.models.goal import GoalPriority
from app.db.models.plan import Plan, PlanItem, PlanStatus
from app.db.models.task import GoalDecomposition, Task, TaskDependency
from app.db.models.user import User
from app.schemas.plan import (
    PlanCreateRequest,
    PlanItemResponse,
    PlanListResponse,
    PlanResponse,
    PlanSummaryResponse,
)
from app.services.critical_path import CriticalPathService
from app.services.dependency_graph import DependencyGraphService
from app.services.goal import GoalService

logger = logging.getLogger("lifethread.services.planning")

PRIORITY_WEIGHTS: dict[GoalPriority, int] = {
    GoalPriority.CRITICAL: 4,
    GoalPriority.HIGH: 3,
    GoalPriority.MEDIUM: 2,
    GoalPriority.LOW: 1,
}


class PlanningService:
    """Core domain service for deterministic scheduling, capacity allocation, and plan versioning."""

    @classmethod
    async def generate_plan(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        request: PlanCreateRequest,
    ) -> PlanResponse:
        """Generate a versioned execution schedule allocating tasks across time and available capacity."""
        # 1. Verify goal exists and belongs to the authenticated user
        goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)

        # 2. Identify active decomposition version and fetch its tasks and dependencies
        decomp_q = (
            select(GoalDecomposition)
            .where(GoalDecomposition.goal_id == goal_id, GoalDecomposition.is_active.is_(True))
            .order_by(GoalDecomposition.version.desc())
        )
        decomp_res = await db.execute(decomp_q)
        active_decomp = decomp_res.scalars().first()

        target_version = active_decomp.version if active_decomp else 1

        tasks_q = (
            select(Task)
            .where(Task.goal_id == goal_id, Task.version == target_version)
            .options(
                selectinload(Task.outgoing_dependencies),
                selectinload(Task.incoming_dependencies),
            )
        )
        tasks_res = await db.execute(tasks_q)
        tasks = tasks_res.scalars().all()

        if not tasks:
            raise LifeThreadException(
                message="Cannot generate plan: Goal has no decomposed tasks. Please run decomposition first.",
                code="NO_TASKS_FOR_PLANNING",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        task_ids = [t.id for t in tasks]
        task_map = {t.id: t for t in tasks}

        # 3. Retrieve dependencies for these tasks
        deps_q = select(TaskDependency).where(TaskDependency.task_id.in_(task_ids))
        deps_res = await db.execute(deps_q)
        dependencies = deps_res.scalars().all()

        edges = [(d.depends_on_task_id, d.task_id) for d in dependencies]

        # 4. Topological sort and Critical Path calculation
        topological_order = DependencyGraphService.topological_sort(task_ids, edges)
        critical_path_ids, _, schedules = CriticalPathService.calculate_critical_path(
            tasks=tasks,
            dependencies=edges,
            topological_order=topological_order,
        )
        critical_path_set = set(critical_path_ids)

        # 5. Resolve user timezone and base schedule start
        try:
            user_res = await db.execute(select(User).where(User.id == user_id))
            user_obj = user_res.scalar_one_or_none()
            tz_str = user_obj.timezone if user_obj and user_obj.timezone else "UTC"
            user_tz = ZoneInfo(tz_str)
        except (ZoneInfoNotFoundError, ValueError):
            user_tz = ZoneInfo("UTC")

        plan_start = request.start_date or datetime.now(UTC)
        if plan_start.tzinfo is None:
            plan_start = plan_start.replace(tzinfo=UTC)

        # 6. Execute deterministic calendar scheduling
        scheduled_items, plan_end, total_capacity_minutes = cls._schedule_tasks_calendar(
            tasks=tasks,
            task_map=task_map,
            edges=edges,
            topological_order=topological_order,
            critical_path_set=critical_path_set,
            plan_start=plan_start,
            user_tz=user_tz,
            daily_available_hours=request.daily_available_hours,
            workdays_only=request.workdays_only,
            daily_start_hour=request.daily_start_hour,
        )

        total_task_minutes = sum(t.estimated_minutes for t in tasks)

        # 7. Evaluate Feasibility and Deadline Risk
        is_feasible = True
        infeasibility_reasons: list[str] = []

        if goal.deadline is not None:
            goal_deadline_utc = goal.deadline
            if goal_deadline_utc.tzinfo is None:
                goal_deadline_utc = goal_deadline_utc.replace(tzinfo=UTC)

            if plan_end > goal_deadline_utc:
                is_feasible = False
                overrun_hours = round((plan_end - goal_deadline_utc).total_seconds() / 3600, 1)
                infeasibility_reasons.append(
                    f"Scheduled completion ({plan_end.isoformat()}) exceeds goal deadline "
                    f"({goal_deadline_utc.isoformat()}) by {overrun_hours} hours."
                )

        # Calculate deadline risk score & category
        deadline_risk, risk_level = cls._calculate_deadline_risk(
            plan_start=plan_start,
            plan_end=plan_end,
            deadline=goal.deadline,
        )

        # Calculate schedule capacity utilization
        utilization = 0.0
        if total_capacity_minutes > 0:
            utilization = round(min(1.0, total_task_minutes / total_capacity_minutes), 3)

        # 8. Manage Versioning and preserve historical plans
        max_v_q = select(func.max(Plan.version)).where(Plan.goal_id == goal_id)
        max_v_res = await db.execute(max_v_q)
        max_existing_v = max_v_res.scalar() or 0
        new_version = max_existing_v + 1

        # Mark previous active plans as SUPERSEDED
        existing_plans_q = select(Plan).where(
            Plan.goal_id == goal_id, Plan.status == PlanStatus.ACTIVE
        )
        existing_plans_res = await db.execute(existing_plans_q)
        for ep in existing_plans_res.scalars().all():
            ep.status = PlanStatus.SUPERSEDED

        plan_status = PlanStatus.ACTIVE if is_feasible else PlanStatus.INFEASIBLE
        plan_reason = request.reason or (
            "Initial generated schedule" if new_version == 1 else f"Revision {new_version}"
        )
        if not is_feasible:
            plan_reason = f"INFEASIBLE: {'; '.join(infeasibility_reasons)}"

        # 9. Persist Plan and PlanItems
        plan_model = Plan(
            goal_id=goal_id,
            version=new_version,
            status=plan_status,
            reason=plan_reason,
            is_feasible=is_feasible,
            deadline_risk=deadline_risk,
            risk_level=risk_level,
            schedule_utilization=utilization,
            total_duration_minutes=total_task_minutes,
            scheduled_start=plan_start,
            scheduled_end=plan_end,
            metadata_={
                "daily_available_hours": request.daily_available_hours,
                "workdays_only": request.workdays_only,
                "daily_start_hour": request.daily_start_hour,
                "infeasibility_reasons": infeasibility_reasons,
                "total_capacity_minutes": total_capacity_minutes,
            },
        )
        db.add(plan_model)
        await db.flush()

        plan_item_models: list[PlanItem] = []
        for item_data in scheduled_items:
            pi = PlanItem(
                plan_id=plan_model.id,
                task_id=item_data["task_id"],
                scheduled_start=item_data["start"],
                scheduled_end=item_data["end"],
                priority=item_data["priority"],
                rationale=item_data["rationale"],
            )
            db.add(pi)
            plan_item_models.append(pi)

        await db.flush()

        # Build response
        item_responses: list[PlanItemResponse] = []
        for pi in plan_item_models:
            task_title = task_map[pi.task_id].title if pi.task_id in task_map else None
            item_responses.append(
                PlanItemResponse(
                    id=pi.id,
                    plan_id=pi.plan_id,
                    task_id=pi.task_id,
                    task_title=task_title,
                    scheduled_start=pi.scheduled_start,
                    scheduled_end=pi.scheduled_end,
                    priority=pi.priority,
                    rationale=pi.rationale,
                )
            )

        return PlanResponse(
            id=plan_model.id,
            goal_id=plan_model.goal_id,
            version=plan_model.version,
            status=plan_model.status,
            generated_at=plan_model.generated_at,
            reason=plan_model.reason,
            is_feasible=plan_model.is_feasible,
            deadline_risk=plan_model.deadline_risk,
            risk_level=plan_model.risk_level,
            schedule_utilization=plan_model.schedule_utilization,
            total_duration_minutes=plan_model.total_duration_minutes,
            scheduled_start=plan_model.scheduled_start,
            scheduled_end=plan_model.scheduled_end,
            items=item_responses,
            metadata=plan_model.metadata_,
        )

    @classmethod
    def _schedule_tasks_calendar(
        cls,
        tasks: list[Task],
        task_map: dict[uuid.UUID, Task],
        edges: list[tuple[uuid.UUID, uuid.UUID]],
        topological_order: list[uuid.UUID],
        critical_path_set: set[uuid.UUID],
        plan_start: datetime,
        user_tz: ZoneInfo,
        daily_available_hours: float,
        workdays_only: bool,
        daily_start_hour: int,
    ) -> tuple[list[dict[str, Any]], datetime, int]:
        """Execute deterministic forward calendar scheduling respecting prerequisites and daily working capacity."""
        daily_capacity_minutes = int(daily_available_hours * 60)

        # Build prerequisites lookup: task_id -> list of prereq_ids
        prereqs_of: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for prereq_id, t_id in edges:
            prereqs_of[t_id].append(prereq_id)

        # Track completed task finish times
        task_finish_times: dict[uuid.UUID, datetime] = {}
        scheduled_items: list[dict[str, Any]] = []

        # Order ready tasks using Topological, Critical Path, and Priority criteria
        # We process along topological order ensuring prerequisites are scheduled first
        processed_tasks: set[uuid.UUID] = set()
        current_cursor = plan_start

        def get_work_window(local_dt: datetime) -> tuple[datetime, datetime]:
            work_start = local_dt.replace(hour=daily_start_hour, minute=0, second=0, microsecond=0)
            work_end = work_start + timedelta(minutes=daily_capacity_minutes)
            return work_start, work_end

        # Helper to get start of next valid work day window
        def advance_to_work_window(dt: datetime) -> datetime:
            local_dt = dt.astimezone(user_tz)
            while True:
                is_weekend = local_dt.weekday() >= 5
                if workdays_only and is_weekend:
                    local_dt = (local_dt + timedelta(days=1)).replace(
                        hour=daily_start_hour, minute=0, second=0, microsecond=0
                    )
                    continue

                work_start, work_end = get_work_window(local_dt)
                if local_dt < work_start:
                    local_dt = work_start
                    break
                if local_dt >= work_end:
                    local_dt = (local_dt + timedelta(days=1)).replace(
                        hour=daily_start_hour, minute=0, second=0, microsecond=0
                    )
                    continue
                break

            return local_dt.astimezone(UTC)

        def compute_task_end(start_dt: datetime, duration_minutes: int) -> datetime:
            curr_local = start_dt.astimezone(user_tz)
            rem = duration_minutes
            while rem > 0:
                work_start, work_end = get_work_window(curr_local)
                if curr_local < work_start:
                    curr_local = work_start
                avail_today = max(0, int((work_end - curr_local).total_seconds() / 60))
                if avail_today <= 0:
                    curr_local = advance_to_work_window(curr_local.astimezone(UTC)).astimezone(
                        user_tz
                    )
                    continue
                if rem <= avail_today:
                    curr_local = curr_local + timedelta(minutes=rem)
                    rem = 0
                else:
                    rem -= avail_today
                    next_day = curr_local + timedelta(days=1)
                    curr_local = advance_to_work_window(next_day.astimezone(UTC)).astimezone(
                        user_tz
                    )
            return curr_local.astimezone(UTC)

        current_cursor = advance_to_work_window(current_cursor)

        for task_id in topological_order:
            task = task_map[task_id]
            prereq_ids = prereqs_of[task_id]

            # Prerequisite readiness constraint: cannot start before all prerequisites finish
            earliest_prereq_finish = plan_start
            prereq_names = []
            for pid in prereq_ids:
                if pid in task_finish_times:
                    if task_finish_times[pid] > earliest_prereq_finish:
                        earliest_prereq_finish = task_finish_times[pid]
                    prereq_names.append(task_map[pid].title)

            # Start time is max of earliest_prereq_finish and current_cursor
            candidate_start = max(current_cursor, earliest_prereq_finish)
            candidate_start = advance_to_work_window(candidate_start)

            # Compute finish time respecting daily available working hours
            duration = max(1, task.estimated_minutes)
            task_end = compute_task_end(candidate_start, duration)

            task_finish_times[task_id] = task_end
            current_cursor = task_end
            processed_tasks.add(task_id)

            # Build rationale explaining decision
            is_critical = task_id in critical_path_set
            rationale_parts = []
            if prereq_names:
                rationale_parts.append(
                    f"Scheduled after completion of prerequisite(s): {', '.join(prereq_names)}."
                )
            else:
                rationale_parts.append("Initial root task with no prerequisites.")

            if is_critical:
                rationale_parts.append("Prioritized on Critical Path to prevent project delay.")
            else:
                rationale_parts.append(f"Ranked with {task.priority.value} priority.")

            scheduled_items.append(
                {
                    "task_id": task_id,
                    "start": candidate_start,
                    "end": task_end,
                    "priority": task.priority,
                    "rationale": " ".join(rationale_parts),
                }
            )

        overall_plan_end = max([item["end"] for item in scheduled_items], default=plan_start)

        # Compute total capacity minutes across the scheduled span
        total_days = max(1, (overall_plan_end.date() - plan_start.date()).days + 1)
        total_capacity_minutes = total_days * daily_capacity_minutes

        return scheduled_items, overall_plan_end, total_capacity_minutes

    @classmethod
    def _calculate_deadline_risk(
        cls,
        plan_start: datetime,
        plan_end: datetime,
        deadline: datetime | None,
    ) -> tuple[float, str]:
        """Quantify deadline risk ratio and categorical risk level."""
        if deadline is None:
            return 0.0, "LOW"

        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)

        total_window_sec = (deadline - plan_start).total_seconds()
        if total_window_sec <= 0:
            return 1.0, "CRITICAL"

        scheduled_span_sec = (plan_end - plan_start).total_seconds()
        risk_score = round(scheduled_span_sec / total_window_sec, 3)

        if risk_score > 1.0 or plan_end > deadline:
            return risk_score, "CRITICAL"
        if risk_score >= 0.85:
            return risk_score, "HIGH"
        if risk_score >= 0.65:
            return risk_score, "MEDIUM"
        return risk_score, "LOW"

    @classmethod
    async def get_active_plan(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> PlanResponse:
        """Retrieve the current active plan for a goal."""
        await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)

        query = (
            select(Plan)
            .where(
                Plan.goal_id == goal_id, Plan.status.in_([PlanStatus.ACTIVE, PlanStatus.INFEASIBLE])
            )
            .options(selectinload(Plan.items))
            .order_by(Plan.version.desc())
        )
        result = await db.execute(query)
        plan = result.scalars().first()

        if plan is None:
            raise LifeThreadException(
                message="No active plan found for this goal. Please generate a plan first.",
                code="PLAN_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return PlanResponse.model_validate(plan)

    @classmethod
    async def list_plans(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> PlanListResponse:
        """List historical plan revisions for a goal."""
        await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)

        query = (
            select(Plan)
            .where(Plan.goal_id == goal_id)
            .options(selectinload(Plan.items))
            .order_by(Plan.version.desc())
        )
        result = await db.execute(query)
        plans = result.scalars().all()

        summaries = [
            PlanSummaryResponse(
                id=p.id,
                goal_id=p.goal_id,
                version=p.version,
                status=p.status,
                generated_at=p.generated_at,
                reason=p.reason,
                is_feasible=p.is_feasible,
                risk_level=p.risk_level,
                total_duration_minutes=p.total_duration_minutes,
                task_count=len(p.items),
                scheduled_start=p.scheduled_start,
                scheduled_end=p.scheduled_end,
            )
            for p in plans
        ]

        return PlanListResponse(goal_id=goal_id, items=summaries, total=len(summaries))

    @classmethod
    async def get_plan_by_version(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        version: int,
    ) -> PlanResponse:
        """Retrieve a specific historical plan version for a goal."""
        await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)

        query = (
            select(Plan)
            .where(Plan.goal_id == goal_id, Plan.version == version)
            .options(selectinload(Plan.items))
        )
        result = await db.execute(query)
        plan = result.scalars().first()

        if plan is None:
            raise LifeThreadException(
                message=f"Plan version {version} not found for this goal",
                code="PLAN_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return PlanResponse.model_validate(plan)
