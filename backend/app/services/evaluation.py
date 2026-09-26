import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.goal import Goal, GoalPriority
from app.db.models.task import GoalDecomposition, Task, TaskDependency, TaskStatus
from app.schemas.evaluation import (
    GoalProgressEvaluation,
    GoalRiskEvaluation,
    GoalWeaknessesEvaluation,
    TaskEvaluation,
    WeaknessItem,
)
from app.services.critical_path import CriticalPathService
from app.services.dependency_graph import DependencyGraphService
from app.services.goal import GoalService

logger = logging.getLogger("lifethread.services.evaluation")

PRIORITY_WEIGHTS: dict[GoalPriority, int] = {
    GoalPriority.CRITICAL: 4,
    GoalPriority.HIGH: 3,
    GoalPriority.MEDIUM: 2,
    GoalPriority.LOW: 1,
}


class EvaluationService:
    """Core domain service for deterministic goal, task, progress, and risk evaluations."""

    @classmethod
    async def _fetch_goal_and_tasks(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> tuple[Goal, list[Task], list[TaskDependency], list[uuid.UUID]]:
        """Helper to retrieve goal, active tasks, dependencies, and critical path task IDs."""
        goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)

        # Retrieve active decomposition version if present
        decomp_q = (
            select(GoalDecomposition)
            .where(GoalDecomposition.goal_id == goal_id, GoalDecomposition.is_active.is_(True))
            .order_by(GoalDecomposition.version.desc())
        )
        decomp_res = await db.execute(decomp_q)
        active_decomp = decomp_res.scalars().first()
        target_version = active_decomp.version if active_decomp else 1

        # Fetch tasks
        tasks_q = (
            select(Task)
            .where(Task.goal_id == goal_id, Task.version == target_version)
            .options(
                selectinload(Task.outgoing_dependencies),
                selectinload(Task.incoming_dependencies),
            )
        )
        tasks_res = await db.execute(tasks_q)
        tasks = list(tasks_res.scalars().all())

        task_ids = [t.id for t in tasks]
        dependencies: list[TaskDependency] = []
        critical_path_ids: list[uuid.UUID] = []

        if task_ids:
            deps_q = select(TaskDependency).where(TaskDependency.task_id.in_(task_ids))
            deps_res = await db.execute(deps_q)
            dependencies = list(deps_res.scalars().all())
            edges = [(d.depends_on_task_id, d.task_id) for d in dependencies]

            try:
                topological_order = DependencyGraphService.topological_sort(task_ids, edges)
                critical_path_ids, _, _ = CriticalPathService.calculate_critical_path(
                    tasks=tasks,
                    dependencies=edges,
                    topological_order=topological_order,
                )
            except Exception as e:
                logger.warning("Could not calculate critical path for goal %s: %s", goal_id, e)
                critical_path_ids = []

        return goal, tasks, dependencies, critical_path_ids

    @classmethod
    async def evaluate_progress(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> GoalProgressEvaluation:
        """Evaluate progress taking into account task completion, priority weights, deadlines, and blockers."""
        goal, tasks, dependencies, critical_path_ids = await cls._fetch_goal_and_tasks(
            db=db, goal_id=goal_id, user_id=user_id
        )

        total_tasks = len(tasks)
        if total_tasks == 0:
            return GoalProgressEvaluation(
                goal_id=goal_id,
                goal_progress=0.0,
                raw_task_progress=0.0,
                total_tasks=0,
                completed_tasks=0,
                in_progress_tasks=0,
                pending_tasks=0,
                blocked_tasks=0,
                cancelled_tasks=0,
                remaining_workload_minutes=0,
                deadline_risk="low",
                weaknesses=["Goal has no decomposed tasks."],
                recommended_action="Run goal decomposition to generate milestones and actionable tasks.",
            )

        completed_tasks = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        in_progress_tasks = sum(1 for t in tasks if t.status == TaskStatus.IN_PROGRESS)
        pending_tasks = sum(1 for t in tasks if t.status == TaskStatus.PENDING)
        blocked_tasks = sum(1 for t in tasks if t.status == TaskStatus.BLOCKED)
        cancelled_tasks = sum(1 for t in tasks if t.status == TaskStatus.CANCELLED)

        # Priority weighted progress
        total_weight = sum(PRIORITY_WEIGHTS.get(t.priority, 2) for t in tasks)
        earned_weight = sum(
            PRIORITY_WEIGHTS.get(t.priority, 2) * 1.0
            for t in tasks
            if t.status == TaskStatus.COMPLETED
        ) + sum(
            PRIORITY_WEIGHTS.get(t.priority, 2) * 0.25
            for t in tasks
            if t.status == TaskStatus.IN_PROGRESS
        )

        goal_progress = round(earned_weight / total_weight, 2) if total_weight > 0 else 0.0
        raw_task_progress = round(completed_tasks / total_tasks, 2)

        # Remaining workload minutes
        remaining_workload_minutes = sum(
            t.estimated_minutes
            for t in tasks
            if t.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
        )

        # Deadline evaluation
        now = datetime.now(UTC)
        deadline_risk = "low"
        weaknesses_list: list[str] = []

        if goal.deadline is not None:
            dl_utc = (
                goal.deadline
                if goal.deadline.tzinfo is not None
                else goal.deadline.replace(tzinfo=UTC)
            )
            hours_remaining = (dl_utc - now).total_seconds() / 3600.0
            workload_hours = remaining_workload_minutes / 60.0

            if hours_remaining <= 0 and remaining_workload_minutes > 0:
                deadline_risk = "critical"
                weaknesses_list.append(
                    f"Goal deadline passed with {round(workload_hours, 1)}h of workload unfinished."
                )
            elif hours_remaining > 0:
                ratio = workload_hours / max(1.0, hours_remaining * 0.5)
                if ratio > 1.0:
                    deadline_risk = "critical"
                    weaknesses_list.append(
                        f"Remaining workload ({round(workload_hours, 1)}h) exceeds feasible capacity before deadline ({round(hours_remaining, 1)}h remaining)."
                    )
                elif ratio >= 0.75:
                    deadline_risk = "high"
                    weaknesses_list.append(
                        "High deadline pressure: remaining effort approaches available buffer."
                    )
                elif ratio >= 0.45:
                    deadline_risk = "medium"

        if blocked_tasks > 0:
            weaknesses_list.append(f"{blocked_tasks} task(s) currently marked BLOCKED.")
            if deadline_risk == "low":
                deadline_risk = "medium"

        critical_path_set = set(critical_path_ids)
        blocked_on_cp = [
            t.title for t in tasks if t.id in critical_path_set and t.status == TaskStatus.BLOCKED
        ]
        if blocked_on_cp:
            weaknesses_list.append(f"Critical path stall: {', '.join(blocked_on_cp)} blocked.")
            deadline_risk = "critical" if deadline_risk in ("high", "critical") else "high"

        # Overdue tasks
        overdue_tasks = [
            t.title
            for t in tasks
            if t.due_at is not None
            and (t.due_at if t.due_at.tzinfo is not None else t.due_at.replace(tzinfo=UTC)) < now
            and t.status != TaskStatus.COMPLETED
        ]
        if overdue_tasks:
            weaknesses_list.append(
                f"{len(overdue_tasks)} individual task(s) overdue: {', '.join(overdue_tasks[:3])}."
            )

        # Recommended action
        if deadline_risk == "critical":
            recommended_action = (
                "Urgent: Unblock critical path tasks and renegotiate deadline or reduce scope."
            )
        elif blocked_tasks > 0:
            recommended_action = "Prioritize resolving prerequisite dependencies for blocked tasks."
        elif in_progress_tasks == 0 and pending_tasks > 0:
            recommended_action = "Begin execution on ready pending tasks along the critical path."
        elif goal_progress >= 0.9:
            recommended_action = "Finalize remaining tasks and run goal completion verification."
        else:
            recommended_action = "Maintain scheduled momentum on active in-progress tasks."

        return GoalProgressEvaluation(
            goal_id=goal_id,
            goal_progress=goal_progress,
            raw_task_progress=raw_task_progress,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            in_progress_tasks=in_progress_tasks,
            pending_tasks=pending_tasks,
            blocked_tasks=blocked_tasks,
            cancelled_tasks=cancelled_tasks,
            remaining_workload_minutes=remaining_workload_minutes,
            deadline_risk=deadline_risk,
            weaknesses=weaknesses_list,
            recommended_action=recommended_action,
        )

    @classmethod
    async def evaluate_task(
        cls,
        db: AsyncSession,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> TaskEvaluation:
        """Diagnostic evaluation of a single task considering prerequisites, successors, and performance."""
        # Query task and ensure goal ownership
        task_q = (
            select(Task)
            .join(Goal, Task.goal_id == Goal.id)
            .where(Task.id == task_id, Goal.user_id == user_id)
            .options(
                selectinload(Task.outgoing_dependencies),
                selectinload(Task.incoming_dependencies),
            )
        )
        task_res = await db.execute(task_q)
        task = task_res.scalar_one_or_none()

        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found or access denied",
            )

        # Fetch sibling tasks for prerequisite status evaluation
        siblings_q = select(Task).where(Task.goal_id == task.goal_id, Task.version == task.version)
        siblings_res = await db.execute(siblings_q)
        task_map = {t.id: t for t in siblings_res.scalars().all()}

        # Prerequisite analysis: outgoing_dependencies means this task depends on depends_on_task_id
        uncompleted_prereqs = []
        for dep in task.outgoing_dependencies:
            prereq = task_map.get(dep.depends_on_task_id)
            if prereq and prereq.status != TaskStatus.COMPLETED:
                uncompleted_prereqs.append(
                    {
                        "task_id": str(prereq.id),
                        "title": prereq.title,
                        "status": prereq.status.value,
                        "priority": prereq.priority.value,
                    }
                )

        is_blocked_by_prereqs = len(uncompleted_prereqs) > 0
        dependent_tasks_count = len(task.incoming_dependencies)

        # Critical path calculation
        deps_q = select(TaskDependency).where(TaskDependency.task_id.in_(list(task_map.keys())))
        deps_res = await db.execute(deps_q)
        dependencies = list(deps_res.scalars().all())
        edges = [(d.depends_on_task_id, d.task_id) for d in dependencies]

        is_on_cp = False
        try:
            order = DependencyGraphService.topological_sort(list(task_map.keys()), edges)
            cp_ids, _, _ = CriticalPathService.calculate_critical_path(
                tasks=list(task_map.values()),
                dependencies=edges,
                topological_order=order,
            )
            is_on_cp = task.id in set(cp_ids)
        except Exception:
            is_on_cp = False

        # Overdue analysis
        now = datetime.now(UTC)
        is_overdue = False
        if task.due_at is not None and task.status != TaskStatus.COMPLETED:
            due_utc = (
                task.due_at if task.due_at.tzinfo is not None else task.due_at.replace(tzinfo=UTC)
            )
            is_overdue = due_utc < now

        # Risk and issues identification
        issues: list[str] = []
        if task.status == TaskStatus.BLOCKED:
            issues.append("Task is explicitly flagged as BLOCKED.")
        if is_overdue:
            issues.append(
                f"Task deadline expired ({task.due_at.isoformat() if task.due_at else ''})."
            )
        if is_blocked_by_prereqs:
            issues.append(
                f"Waiting on {len(uncompleted_prereqs)} uncompleted prerequisite task(s)."
            )
        if is_on_cp:
            issues.append("Task is on Critical Path; delay here delays entire goal.")

        if task.status == TaskStatus.COMPLETED:
            risk_level = "low"
            recommended_action = "Task completed successfully. No action required."
        elif task.status == TaskStatus.BLOCKED or (
            is_on_cp and (is_overdue or is_blocked_by_prereqs)
        ):
            risk_level = "critical"
            recommended_action = (
                "Immediate intervention: resolve prerequisite blockers to prevent project delay."
            )
        elif is_overdue or is_blocked_by_prereqs or task.priority == GoalPriority.CRITICAL:
            risk_level = "high"
            recommended_action = "Accelerate execution and clear upstream prerequisites."
        elif task.status == TaskStatus.IN_PROGRESS:
            risk_level = "low"
            recommended_action = "Continue active execution to completion."
        else:
            risk_level = "low"
            recommended_action = "Ready for execution when scheduled capacity permits."

        return TaskEvaluation(
            task_id=task.id,
            goal_id=task.goal_id,
            title=task.title,
            status=task.status,
            priority=task.priority,
            estimated_minutes=task.estimated_minutes,
            is_overdue=is_overdue,
            is_blocked_by_prerequisites=is_blocked_by_prereqs,
            uncompleted_prerequisites=uncompleted_prereqs,
            dependent_tasks_count=dependent_tasks_count,
            is_on_critical_path=is_on_cp,
            risk_level=risk_level,
            issues=issues,
            recommended_action=recommended_action,
        )

    @classmethod
    async def identify_weakness(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> GoalWeaknessesEvaluation:
        """Scan goal structure and execution status to pinpoint specific vulnerabilities."""
        goal, tasks, dependencies, critical_path_ids = await cls._fetch_goal_and_tasks(
            db=db, goal_id=goal_id, user_id=user_id
        )

        weaknesses: list[WeaknessItem] = []
        now = datetime.now(UTC)
        critical_path_set = set(critical_path_ids)

        # 1. Blocked execution items
        blocked_tasks = [t for t in tasks if t.status == TaskStatus.BLOCKED]
        if blocked_tasks:
            severity = (
                "CRITICAL" if any(t.id in critical_path_set for t in blocked_tasks) else "HIGH"
            )
            weaknesses.append(
                WeaknessItem(
                    category="BLOCKED_EXECUTION",
                    severity=severity,
                    description=f"{len(blocked_tasks)} task(s) currently marked as BLOCKED.",
                    affected_task_ids=[t.id for t in blocked_tasks],
                    mitigation_strategy="Identify and resolve blocker root causes or reassign dependencies.",
                )
            )

        # 2. Recent failures / cancelled tasks
        cancelled_tasks = [t for t in tasks if t.status == TaskStatus.CANCELLED]
        if cancelled_tasks:
            weaknesses.append(
                WeaknessItem(
                    category="RECENT_FAILURE",
                    severity="MEDIUM",
                    description=f"{len(cancelled_tasks)} task(s) cancelled or failed during execution.",
                    affected_task_ids=[t.id for t in cancelled_tasks],
                    mitigation_strategy="Review whether cancelled deliverables impact downstream requirements.",
                )
            )

        # 3. Overdue tasks
        overdue_tasks = [
            t
            for t in tasks
            if t.due_at is not None
            and (t.due_at if t.due_at.tzinfo is not None else t.due_at.replace(tzinfo=UTC)) < now
            and t.status != TaskStatus.COMPLETED
        ]
        if overdue_tasks:
            severity = (
                "CRITICAL" if any(t.id in critical_path_set for t in overdue_tasks) else "HIGH"
            )
            weaknesses.append(
                WeaknessItem(
                    category="OVERDUE_TASK",
                    severity=severity,
                    description=f"{len(overdue_tasks)} task(s) overdue past their target due date.",
                    affected_task_ids=[t.id for t in overdue_tasks],
                    mitigation_strategy="Reprioritize overdue tasks and update scheduling expectations.",
                )
            )

        # 4. Dependency bottlenecks (tasks blocking 2 or more downstream tasks)
        successors_count: dict[uuid.UUID, int] = defaultdict(int)
        for d in dependencies:
            successors_count[d.depends_on_task_id] += 1

        bottleneck_tasks = [
            t for t in tasks if successors_count[t.id] >= 2 and t.status != TaskStatus.COMPLETED
        ]
        if bottleneck_tasks:
            weaknesses.append(
                WeaknessItem(
                    category="DEPENDENCY_BOTTLENECK",
                    severity="HIGH",
                    description=f"{len(bottleneck_tasks)} task(s) are gating multiple downstream dependencies.",
                    affected_task_ids=[t.id for t in bottleneck_tasks],
                    mitigation_strategy="Focus execution velocity on bottleneck tasks to unlock downstream queues.",
                )
            )

        # 5. Deadline and capacity overrun
        if goal.deadline is not None:
            dl_utc = (
                goal.deadline
                if goal.deadline.tzinfo is not None
                else goal.deadline.replace(tzinfo=UTC)
            )
            hours_left = (dl_utc - now).total_seconds() / 3600.0
            remaining_mins = sum(
                t.estimated_minutes
                for t in tasks
                if t.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
            )
            workload_hours = remaining_mins / 60.0

            if hours_left <= 0 and remaining_mins > 0:
                weaknesses.append(
                    WeaknessItem(
                        category="DEADLINE_OVERRUN",
                        severity="CRITICAL",
                        description=f"Goal deadline has lapsed with {round(workload_hours, 1)} hours of workload unfinished.",
                        affected_task_ids=[t.id for t in tasks if t.status != TaskStatus.COMPLETED],
                        mitigation_strategy="Immediately extend goal deadline or reduce scope.",
                    )
                )
            elif hours_left > 0 and workload_hours > (hours_left * 0.5):
                weaknesses.append(
                    WeaknessItem(
                        category="DEADLINE_OVERRUN",
                        severity="HIGH",
                        description=f"Remaining effort ({round(workload_hours, 1)}h) exceeds safe capacity margin before deadline.",
                        affected_task_ids=[t.id for t in tasks if t.status != TaskStatus.COMPLETED],
                        mitigation_strategy="Adjust daily available hours or prune non-critical tasks.",
                    )
                )

        # Determine overall health
        has_critical = any(w.severity == "CRITICAL" for w in weaknesses)
        has_high = any(w.severity == "HIGH" for w in weaknesses)
        has_medium = any(w.severity == "MEDIUM" for w in weaknesses)

        if has_critical:
            overall_health = "CRITICAL"
            recommended_action = "Execute immediate recovery interventions on critical bottlenecks and overdue items."
        elif has_high:
            overall_health = "AT_RISK"
            recommended_action = (
                "Clear active blockers and accelerate unblocking dependent workflows."
            )
        elif has_medium:
            overall_health = "NEEDS_ATTENTION"
            recommended_action = "Monitor velocity and ensure tasks with multiple dependencies are scheduled promptly."
        else:
            overall_health = "HEALTHY"
            recommended_action = "Plan execution is on track; continue steady progress."

        return GoalWeaknessesEvaluation(
            goal_id=goal_id,
            weaknesses=weaknesses,
            weakness_count=len(weaknesses),
            overall_health=overall_health,
            recommended_action=recommended_action,
        )

    @classmethod
    async def calculate_goal_risk(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> GoalRiskEvaluation:
        """Calculate multivariate risk composite quantifying exposure across schedule, dependencies, and priority."""
        goal, tasks, dependencies, critical_path_ids = await cls._fetch_goal_and_tasks(
            db=db, goal_id=goal_id, user_id=user_id
        )

        if not tasks:
            return GoalRiskEvaluation(
                goal_id=goal_id,
                composite_risk_score=0.0,
                deadline_risk="low",
                schedule_risk_score=0.0,
                dependency_risk_score=0.0,
                priority_risk_score=0.0,
                risk_factors=["Goal has no tasks decomposed yet."],
                recommended_action="Decompose goal to establish execution baseline.",
            )

        now = datetime.now(UTC)
        risk_factors: list[str] = []

        # 1. Schedule risk calculation
        remaining_minutes = sum(
            t.estimated_minutes
            for t in tasks
            if t.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
        )
        workload_hours = remaining_minutes / 60.0
        schedule_risk = 0.1

        if goal.deadline is not None:
            dl_utc = (
                goal.deadline
                if goal.deadline.tzinfo is not None
                else goal.deadline.replace(tzinfo=UTC)
            )
            hours_left = (dl_utc - now).total_seconds() / 3600.0

            if hours_left <= 0:
                schedule_risk = 1.0 if remaining_minutes > 0 else 0.0
                risk_factors.append("Goal deadline has expired.")
            else:
                ratio = workload_hours / max(1.0, hours_left * 0.5)
                schedule_risk = min(1.0, round(ratio, 2))
                if schedule_risk >= 0.7:
                    risk_factors.append(
                        f"High ratio of remaining work to time before deadline ({schedule_risk})."
                    )
        else:
            schedule_risk = 0.2

        # 2. Dependency blocker risk
        critical_path_set = set(critical_path_ids)
        blocked_tasks = [t for t in tasks if t.status == TaskStatus.BLOCKED]
        blocked_on_cp = [t for t in blocked_tasks if t.id in critical_path_set]

        dependency_risk = 0.0
        if blocked_on_cp:
            dependency_risk = 0.95
            risk_factors.append(
                f"{len(blocked_on_cp)} task(s) blocked directly on the critical path."
            )
        elif blocked_tasks:
            dependency_risk = min(0.7, 0.25 * len(blocked_tasks))
            risk_factors.append(f"{len(blocked_tasks)} task(s) blocked.")
        else:
            dependency_risk = 0.1

        # 3. Priority risk
        uncompleted_critical = [
            t
            for t in tasks
            if t.priority == GoalPriority.CRITICAL
            and t.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
        ]
        uncompleted_high = [
            t
            for t in tasks
            if t.priority == GoalPriority.HIGH
            and t.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
        ]

        priority_risk = 0.1
        if uncompleted_critical:
            priority_risk = min(1.0, 0.5 + (0.15 * len(uncompleted_critical)))
            risk_factors.append(f"{len(uncompleted_critical)} CRITICAL priority task(s) remaining.")
        elif uncompleted_high:
            priority_risk = min(0.7, 0.25 + (0.08 * len(uncompleted_high)))

        # Composite score
        composite_score = round(
            (0.40 * schedule_risk) + (0.35 * dependency_risk) + (0.25 * priority_risk), 2
        )
        composite_score = max(0.0, min(1.0, composite_score))

        # Categorical rating
        if composite_score >= 0.75:
            deadline_risk = "critical"
            recommended_action = (
                "Emergency mitigation: unblock critical path bottlenecks and extend timeline."
            )
        elif composite_score >= 0.55:
            deadline_risk = "high"
            recommended_action = (
                "Intensify effort on high-priority prerequisites and mitigate blockers."
            )
        elif composite_score >= 0.35:
            deadline_risk = "medium"
            recommended_action = "Monitor progress and keep active dependencies unblocked."
        else:
            deadline_risk = "low"
            recommended_action = "Plan execution risk is within healthy tolerances."

        return GoalRiskEvaluation(
            goal_id=goal_id,
            composite_risk_score=composite_score,
            deadline_risk=deadline_risk,
            schedule_risk_score=round(schedule_risk, 2),
            dependency_risk_score=round(dependency_risk, 2),
            priority_risk_score=round(priority_risk, 2),
            risk_factors=risk_factors,
            recommended_action=recommended_action,
        )
