import logging
import math
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.goal import Goal, GoalPriority
from app.db.models.task import GoalDecomposition, Task, TaskDependency, TaskStatus
from app.services.critical_path import CriticalPathService
from app.services.dependency_graph import DependencyGraphService
from app.services.goal import GoalService
from app.services.goal_evaluation.models import (
    GoalEvaluation,
    RiskAssessment,
    TaskEvaluation,
    Weakness,
)

logger = logging.getLogger("lifethread.services.goal_evaluation")

PRIORITY_BASE_WEIGHTS: dict[GoalPriority, float] = {
    GoalPriority.CRITICAL: 4.0,
    GoalPriority.HIGH: 3.0,
    GoalPriority.MEDIUM: 2.0,
    GoalPriority.LOW: 1.0,
}


class GoalEvaluationEngine:
    """Advanced Goal Evaluation Engine for LifeThread.

    Evaluates whether the user's current plan is actually moving the goal forward,
    computing weighted progress, performance, consistency, deadline risk,
    blocked dependencies, recent failures, and remaining workload with deterministic confidence.
    """

    @classmethod
    def compute_task_weight(
        cls,
        task: Task,
        is_on_critical_path: bool = False,
    ) -> float:
        """Compute multi-factor weight for a task based on priority, workload, and critical path."""
        p_weight = PRIORITY_BASE_WEIGHTS.get(task.priority, 2.0)

        # Workload factor: logarithmic scaling so a 10-hour task matters more than a 15-minute task
        # without completely dwarfing smaller critical milestones
        est = max(15, task.estimated_minutes if task.estimated_minutes else 30)
        workload_factor = math.log2(est / 15.0) + 1.0  # 15m -> 1.0, 60m -> 3.0, 4h -> 5.0

        cp_multiplier = 1.35 if is_on_critical_path else 1.0
        return round(p_weight * workload_factor * cp_multiplier, 3)

    @classmethod
    def evaluate_plan_data(
        cls,
        goal: Goal,
        tasks: list[Task],
        dependencies: list[TaskDependency],
        critical_path_ids: list[uuid.UUID],
        execution_history: list[dict[str, Any]] | None = None,
        as_of: datetime | None = None,
    ) -> GoalEvaluation:
        """Pure, deterministic evaluation of goal execution state against its plan."""
        now = as_of or datetime.now(UTC)
        total_tasks = len(tasks)

        # Empty plan handling
        if total_tasks == 0:
            risk_ass = RiskAssessment(
                overall_risk="HIGH",
                risk_score=0.75,
                confidence=0.90,
                deadline_risk="LOW",
                deadline_risk_score=0.1,
                dependency_risk="LOW",
                dependency_risk_score=0.0,
                failure_risk="LOW",
                failure_risk_score=0.0,
                workload_risk="HIGH",
                workload_risk_score=0.75,
                primary_risk_factors=["No tasks defined in active plan"],
                explanation="The goal has no actionable tasks decomposed. No execution momentum can occur.",
            )
            return GoalEvaluation(
                goal_id=goal.id,
                user_id=goal.user_id,
                is_moving_forward=False,
                completion_ratio=0.0,
                weighted_progress=0.0,
                performance_score=0.0,
                consistency_score=0.0,
                deadline_risk="LOW",
                remaining_workload_minutes=0,
                total_tasks=0,
                completed_tasks=0,
                in_progress_tasks=0,
                blocked_tasks=0,
                failed_tasks=0,
                pending_tasks=0,
                blocked_dependencies_count=0,
                recent_failures_count=0,
                confidence=0.95,
                risk_assessment=risk_ass,
                weaknesses=[
                    Weakness(
                        category="EMPTY_PLAN",
                        severity="HIGH",
                        description="Goal has no actionable decomposition tasks.",
                        mitigation_strategy="Trigger autonomous goal decomposition to generate tasks.",
                        confidence=0.95,
                        impact_score=0.85,
                    )
                ],
                task_evaluations=[],
                major_factors=["Plan contains zero tasks."],
                summary="Goal is dormant: no actionable plan or tasks exist.",
                recommended_action="Decompose goal into actionable tasks and milestones.",
            )

        # Index tasks and dependencies
        task_map = {t.id: t for t in tasks}
        cp_set = set(critical_path_ids)

        # Incoming dependencies: child_task_id -> list of parent_task_ids
        prereqs: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for dep in dependencies:
            if dep.task_id in task_map and dep.depends_on_task_id in task_map:
                prereqs[dep.task_id].append(dep.depends_on_task_id)

        # ---------------------------------------------------------
        # 1. Individual Task Evaluations & Blocked Dependencies
        # ---------------------------------------------------------
        task_evals: list[TaskEvaluation] = []
        blocked_dependencies_count = 0
        recent_failures_count = 0
        failed_tasks_count = 0

        for t in tasks:
            is_cp = t.id in cp_set
            weight = cls.compute_task_weight(t, is_cp)

            # Check prerequisite blockers
            uncompleted_parents = [
                pid for pid in prereqs.get(t.id, []) if task_map[pid].status != TaskStatus.COMPLETED
            ]
            is_blocked = t.status == TaskStatus.BLOCKED or len(uncompleted_parents) > 0
            if uncompleted_parents:
                blocked_dependencies_count += len(uncompleted_parents)

            # Check failures / retries
            metadata = getattr(t, "metadata_json", None) or getattr(t, "metadata", None) or {}
            if not isinstance(metadata, dict):
                metadata = {}
            fail_count = int(metadata.get("failure_count", 0))
            if metadata.get("recent_error") or t.status == TaskStatus.BLOCKED:
                fail_count = max(fail_count, 1)
            has_failed = fail_count > 0 or metadata.get("last_execution_status") == "FAILED"
            if has_failed:
                recent_failures_count += 1
                if t.status in (TaskStatus.BLOCKED, TaskStatus.CANCELLED):
                    failed_tasks_count += 1

            # Check overdue status
            is_overdue = False
            t_due = getattr(t, "due_at", None) or getattr(t, "deadline", None)
            if t_due is not None:
                t_dl = t_due if t_due.tzinfo is not None else t_due.replace(tzinfo=UTC)
                if t_dl < now and t.status != TaskStatus.COMPLETED:
                    is_overdue = True

            # Task performance score
            actual_min = metadata.get("actual_minutes")
            perf_score = 0.85  # Baseline
            if t.status == TaskStatus.COMPLETED:
                if actual_min is not None and t.estimated_minutes > 0:
                    ratio = t.estimated_minutes / max(1, actual_min)
                    perf_score = min(1.0, max(0.2, ratio))
                else:
                    perf_score = 0.95
            elif t.status == TaskStatus.IN_PROGRESS:
                perf_score = 0.75 if not is_overdue else 0.40
            elif t.status == TaskStatus.BLOCKED:
                perf_score = 0.20

            # Task issues
            issues: list[str] = []
            if is_blocked:
                blocking_titles = [
                    task_map[pid].title for pid in uncompleted_parents if pid in task_map
                ]
                if blocking_titles:
                    issues.append(
                        f"Blocked by unsatisfied prerequisites: {', '.join(blocking_titles)}"
                    )
                elif t.status == TaskStatus.BLOCKED:
                    issues.append(metadata.get("block_reason", "Task is in BLOCKED state"))
            if is_overdue:
                issues.append("Task deadline has passed")
            if has_failed:
                issues.append(f"Task has experienced {fail_count} execution failure(s)")
            if is_cp and is_blocked:
                issues.append(
                    "CRITICAL: Task is on the Critical Path and blocking overall progress"
                )

            # Risk tier
            if (is_cp and is_blocked) or (is_overdue and is_cp):
                t_risk = "CRITICAL"
            elif is_blocked or is_overdue or has_failed:
                t_risk = "HIGH"
            elif t.status == TaskStatus.IN_PROGRESS:
                t_risk = "MEDIUM"
            else:
                t_risk = "LOW"

            rec_action = "Execute task"
            if is_blocked:
                rec_action = "Resolve prerequisite blockers before proceeding"
            elif is_overdue:
                rec_action = "Prioritize immediate completion to prevent cascading project delays"
            elif has_failed:
                rec_action = "Inspect error logs, adjust inputs, and retry execution"
            elif t.status == TaskStatus.COMPLETED:
                rec_action = "Task completed successfully"

            # Task confidence based on metadata and estimates
            t_conf = 0.70
            if t.estimated_minutes > 0:
                t_conf += 0.15
            if actual_min is not None or t.status == TaskStatus.COMPLETED:
                t_conf += 0.15

            task_evals.append(
                TaskEvaluation(
                    task_id=t.id,
                    goal_id=goal.id,
                    title=t.title,
                    status=t.status,
                    priority=t.priority,
                    weight=weight,
                    estimated_minutes=t.estimated_minutes,
                    actual_minutes=actual_min,
                    is_overdue=is_overdue,
                    is_blocked=is_blocked,
                    blocked_by_task_ids=uncompleted_parents,
                    has_failed=has_failed,
                    failure_count=fail_count,
                    is_on_critical_path=is_cp,
                    performance_score=round(perf_score, 3),
                    risk_level=t_risk,
                    confidence=round(min(1.0, t_conf), 2),
                    issues=issues,
                    recommended_action=rec_action,
                )
            )

        # ---------------------------------------------------------
        # 2. Completion vs Weighted Progress
        # ---------------------------------------------------------
        completed_tasks = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        in_progress_tasks = sum(1 for t in tasks if t.status == TaskStatus.IN_PROGRESS)
        blocked_tasks = sum(1 for t in task_evals if t.is_blocked)
        pending_tasks = sum(1 for t in tasks if t.status == TaskStatus.PENDING)

        raw_completion_ratio = round(completed_tasks / total_tasks, 4)

        # Active tasks (excluding cancelled)
        active_task_evals = [te for te in task_evals if te.status != TaskStatus.CANCELLED]
        sum_total_weight = sum(te.weight for te in active_task_evals) or 1.0
        earned_weight = 0.0
        for te in active_task_evals:
            if te.status == TaskStatus.COMPLETED:
                earned_weight += te.weight * 1.0
            elif te.status == TaskStatus.IN_PROGRESS:
                earned_weight += te.weight * 0.35  # partial progress credit

        weighted_progress = round(min(1.0, earned_weight / sum_total_weight), 4)

        # ---------------------------------------------------------
        # 3. Remaining Workload
        # ---------------------------------------------------------
        remaining_workload_minutes = sum(
            t.estimated_minutes
            if t.status != TaskStatus.IN_PROGRESS
            else int(t.estimated_minutes * 0.65)
            for t in tasks
            if t.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
        )

        # ---------------------------------------------------------
        # 4. Performance & Consistency Scores
        # ---------------------------------------------------------
        perf_scores = [te.performance_score for te in task_evals]
        overall_performance = round(sum(perf_scores) / len(perf_scores), 4) if perf_scores else 0.70

        # Consistency: penalized by blocked proportion, failure frequency, and CP blockages
        blocked_penalty = (blocked_tasks / total_tasks) * 0.45
        failure_penalty = min(0.35, (recent_failures_count / total_tasks) * 0.40)
        cp_blocked = any(te.is_on_critical_path and te.is_blocked for te in task_evals)
        cp_penalty = 0.20 if cp_blocked else 0.0

        consistency_score = round(
            max(0.0, min(1.0, 1.0 - (blocked_penalty + failure_penalty + cp_penalty))),
            4,
        )

        # ---------------------------------------------------------
        # 5. Deadline Risk Diagnostic
        # ---------------------------------------------------------
        deadline_risk_score = 0.15
        deadline_risk_tier = "LOW"
        hours_remaining: float | None = None

        if goal.deadline is not None:
            dl_utc = (
                goal.deadline
                if goal.deadline.tzinfo is not None
                else goal.deadline.replace(tzinfo=UTC)
            )
            hours_remaining = (dl_utc - now).total_seconds() / 3600.0
            workload_hours = remaining_workload_minutes / 60.0

            if hours_remaining <= 0 and remaining_workload_minutes > 0:
                deadline_risk_score = 1.0
                deadline_risk_tier = "CRITICAL"
            elif hours_remaining > 0:
                # Assuming standard productive work velocity of 5 hours/day (~0.21 hours per calendar hour)
                feasible_hours = max(1.0, hours_remaining * 0.25)
                ratio = workload_hours / feasible_hours
                if ratio >= 1.0:
                    deadline_risk_score = min(1.0, 0.85 + (ratio - 1.0) * 0.15)
                    deadline_risk_tier = "CRITICAL"
                elif ratio >= 0.70:
                    deadline_risk_score = round(0.65 + (ratio - 0.70) * 0.60, 2)
                    deadline_risk_tier = "HIGH"
                elif ratio >= 0.40:
                    deadline_risk_score = round(0.35 + (ratio - 0.40) * 1.0, 2)
                    deadline_risk_tier = "MEDIUM"
                else:
                    deadline_risk_score = round(max(0.05, ratio * 0.8), 2)
                    deadline_risk_tier = "LOW"

        # ---------------------------------------------------------
        # 6. Multi-Factor Risk Assessment
        # ---------------------------------------------------------
        dependency_risk_score = round(
            min(
                1.0,
                (blocked_dependencies_count / max(1, total_tasks)) * 0.7
                + (0.3 if cp_blocked else 0.0),
            ),
            2,
        )
        dep_risk_tier = (
            "CRITICAL"
            if dependency_risk_score >= 0.80
            else (
                "HIGH"
                if dependency_risk_score >= 0.50
                else ("MEDIUM" if dependency_risk_score >= 0.25 else "LOW")
            )
        )

        failure_risk_score = round(min(1.0, (recent_failures_count / max(1, total_tasks)) * 1.2), 2)
        fail_risk_tier = (
            "CRITICAL"
            if failure_risk_score >= 0.75
            else (
                "HIGH"
                if failure_risk_score >= 0.45
                else ("MEDIUM" if failure_risk_score >= 0.20 else "LOW")
            )
        )

        workload_risk_score = round(
            min(1.0, (remaining_workload_minutes / max(120, total_tasks * 90))), 2
        )
        workload_risk_tier = (
            "HIGH"
            if workload_risk_score >= 0.75
            else ("MEDIUM" if workload_risk_score >= 0.40 else "LOW")
        )

        # Composite overall risk
        composite_risk_score = round(
            0.35 * deadline_risk_score
            + 0.30 * dependency_risk_score
            + 0.20 * failure_risk_score
            + 0.15 * (1.0 - consistency_score),
            3,
        )
        if cp_blocked or deadline_risk_tier == "CRITICAL":
            overall_risk_tier = "CRITICAL"
            composite_risk_score = max(composite_risk_score, 0.85)
        elif composite_risk_score >= 0.65 or dep_risk_tier == "HIGH" or fail_risk_tier == "HIGH":
            overall_risk_tier = "HIGH"
        elif composite_risk_score >= 0.35:
            overall_risk_tier = "MEDIUM"
        else:
            overall_risk_tier = "LOW"

        primary_risk_factors: list[str] = []
        if cp_blocked:
            primary_risk_factors.append("Critical Path execution is blocked by unmet dependencies")
        if deadline_risk_tier in ("HIGH", "CRITICAL"):
            rem_h = round(remaining_workload_minutes / 60.0, 1)
            primary_risk_factors.append(f"High deadline pressure with {rem_h}h remaining workload")
        if recent_failures_count > 0:
            primary_risk_factors.append(
                f"{recent_failures_count} task(s) experienced execution failures"
            )
        if blocked_tasks > 0 and not cp_blocked:
            primary_risk_factors.append(f"{blocked_tasks} task(s) are blocked by dependencies")

        risk_explanation = (
            f"Overall plan risk is {overall_risk_tier} (Score: {composite_risk_score:.2f}). "
            f"Deadline risk is {deadline_risk_tier}, dependency risk is {dep_risk_tier}, "
            f"and failure risk is {fail_risk_tier}."
        )

        risk_assessment = RiskAssessment(
            overall_risk=overall_risk_tier,
            risk_score=composite_risk_score,
            confidence=0.88,
            deadline_risk=deadline_risk_tier,
            deadline_risk_score=deadline_risk_score,
            dependency_risk=dep_risk_tier,
            dependency_risk_score=dependency_risk_score,
            failure_risk=fail_risk_tier,
            failure_risk_score=failure_risk_score,
            workload_risk=workload_risk_tier,
            workload_risk_score=workload_risk_score,
            primary_risk_factors=primary_risk_factors,
            explanation=risk_explanation,
        )

        # ---------------------------------------------------------
        # 7. Weaknesses Identification
        # ---------------------------------------------------------
        weaknesses: list[Weakness] = []

        if cp_blocked:
            cp_blocked_tasks = [
                te.task_id for te in task_evals if te.is_on_critical_path and te.is_blocked
            ]
            weaknesses.append(
                Weakness(
                    category="CRITICAL_PATH_BOTTLENECK",
                    severity="CRITICAL",
                    description="One or more critical path tasks are blocked, arresting entire goal delivery timeline.",
                    affected_task_ids=cp_blocked_tasks,
                    mitigation_strategy="Unblock critical path dependencies as the immediate highest priority.",
                    confidence=0.95,
                    impact_score=0.95,
                )
            )

        if deadline_risk_tier in ("HIGH", "CRITICAL"):
            overdue_or_risk_tasks = [
                te.task_id
                for te in task_evals
                if te.is_overdue or te.status != TaskStatus.COMPLETED
            ]
            weaknesses.append(
                Weakness(
                    category="DEADLINE_COMPRESSION",
                    severity="CRITICAL" if deadline_risk_tier == "CRITICAL" else "HIGH",
                    description=f"Remaining workload of {round(remaining_workload_minutes / 60.0, 1)}h is constrained by imminent or passed deadline.",
                    affected_task_ids=overdue_or_risk_tasks[:5],
                    mitigation_strategy="Reprioritize scope or extend goal deadline to prevent failure.",
                    confidence=0.90,
                    impact_score=0.85,
                )
            )

        if recent_failures_count > 0:
            failed_ids = [te.task_id for te in task_evals if te.has_failed]
            weaknesses.append(
                Weakness(
                    category="EXECUTION_FAILURE_CHURN",
                    severity="HIGH" if recent_failures_count >= 2 else "MEDIUM",
                    description=f"{recent_failures_count} task(s) encountered execution errors or repeated retries.",
                    affected_task_ids=failed_ids,
                    mitigation_strategy="Debug failure root causes and adjust tool parameters or task descriptions.",
                    confidence=0.92,
                    impact_score=0.75,
                )
            )

        if blocked_tasks > 0 and not cp_blocked:
            blocked_ids = [te.task_id for te in task_evals if te.is_blocked]
            weaknesses.append(
                Weakness(
                    category="UNRESOLVED_DEPENDENCY",
                    severity="MEDIUM",
                    description=f"{blocked_tasks} task(s) are waiting on prerequisite deliverables.",
                    affected_task_ids=blocked_ids,
                    mitigation_strategy="Complete upstream predecessor tasks to unblock downstream execution.",
                    confidence=0.88,
                    impact_score=0.60,
                )
            )

        # ---------------------------------------------------------
        # 8. Determination: Is the plan moving forward?
        # ---------------------------------------------------------
        # A plan is moving forward if:
        # - It has non-zero progress or active unblocked tasks,
        # - It is NOT deadlocked on the critical path,
        # - Remaining unblocked work exists,
        # - Consistency score is viable (not in failure churn).
        all_remaining_blocked = (total_tasks > completed_tasks) and (
            blocked_tasks >= (total_tasks - completed_tasks)
        )
        is_moving = True

        if cp_blocked:
            is_moving = False
        elif all_remaining_blocked:
            is_moving = False
        elif (
            deadline_risk_tier == "CRITICAL"
            and hours_remaining is not None
            and hours_remaining <= 0
            and remaining_workload_minutes > 0
        ):
            is_moving = False
        elif consistency_score < 0.25 and recent_failures_count > completed_tasks:
            is_moving = False
        elif completed_tasks == 0 and in_progress_tasks == 0 and blocked_tasks > 0:
            is_moving = False

        # ---------------------------------------------------------
        # 9. Major Factors, Summary, and Recommended Action
        # ---------------------------------------------------------
        major_factors: list[str] = [
            f"Weighted progress is {weighted_progress * 100:.1f}% (raw completion: {raw_completion_ratio * 100:.1f}% across {total_tasks} tasks).",
            f"Performance score: {overall_performance * 100:.1f}%, Consistency score: {consistency_score * 100:.1f}%.",
            f"Remaining workload: {remaining_workload_minutes} minutes ({round(remaining_workload_minutes / 60.0, 1)} hours).",
        ]
        if cp_blocked:
            major_factors.append("BLOCKED: Critical path is stalled by unmet dependencies.")
        elif blocked_tasks > 0:
            major_factors.append(
                f"Dependencies: {blocked_tasks} of {total_tasks} tasks are currently blocked."
            )
        if recent_failures_count > 0:
            major_factors.append(
                f"Failures: {recent_failures_count} tasks encountered errors or retry limits."
            )
        if deadline_risk_tier != "LOW":
            major_factors.append(
                f"Deadline risk: {deadline_risk_tier} (remaining hours: {round(hours_remaining, 1) if hours_remaining is not None else 'N/A'})."
            )

        if is_moving:
            summary = (
                f"Plan is actively moving forward with {weighted_progress * 100:.1f}% weighted progress. "
                f"Execution consistency is {consistency_score * 100:.1f}%."
            )
            rec_action = "Continue executing prioritized unblocked tasks according to schedule."
        else:
            summary = (
                f"Plan execution is stalled. Progress cannot advance effectively due to "
                f"{'critical path bottlenecks' if cp_blocked else 'cascading dependency blocks or excessive failures'}."
            )
            rec_action = (
                "Intervene to resolve blocking prerequisite tasks and clear critical path bottlenecks."
                if cp_blocked or blocked_tasks > 0
                else "Review error logs and replan failed tasks to resume forward momentum."
            )

        # Confidence calculation
        has_estimates = sum(1 for t in tasks if t.estimated_minutes > 0) / total_tasks
        has_history = min(
            1.0, (completed_tasks + in_progress_tasks + recent_failures_count) / max(1, total_tasks)
        )
        overall_confidence = round(
            min(1.0, 0.40 + 0.30 * has_estimates + 0.30 * has_history),
            2,
        )

        return GoalEvaluation(
            goal_id=goal.id,
            user_id=goal.user_id,
            is_moving_forward=is_moving,
            completion_ratio=raw_completion_ratio,
            weighted_progress=weighted_progress,
            performance_score=overall_performance,
            consistency_score=consistency_score,
            deadline_risk=deadline_risk_tier,
            remaining_workload_minutes=remaining_workload_minutes,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            in_progress_tasks=in_progress_tasks,
            blocked_tasks=blocked_tasks,
            failed_tasks=failed_tasks_count,
            pending_tasks=pending_tasks,
            blocked_dependencies_count=blocked_dependencies_count,
            recent_failures_count=recent_failures_count,
            confidence=overall_confidence,
            risk_assessment=risk_assessment,
            weaknesses=weaknesses,
            task_evaluations=task_evals,
            major_factors=major_factors,
            summary=summary,
            recommended_action=rec_action,
        )

    @classmethod
    async def evaluate_goal(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        as_of: datetime | None = None,
    ) -> GoalEvaluation:
        """Fetch goal, active decomposition, tasks, and dependencies from DB and evaluate."""
        goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)

        # Retrieve active decomposition version
        decomp_q = (
            select(GoalDecomposition)
            .where(GoalDecomposition.goal_id == goal_id, GoalDecomposition.is_active.is_(True))
            .order_by(GoalDecomposition.version.desc())
        )
        decomp_res = await db.execute(decomp_q)
        active_decomp = decomp_res.scalars().first()
        target_version = active_decomp.version if active_decomp else 1

        # Fetch tasks for active version
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

        return cls.evaluate_plan_data(
            goal=goal,
            tasks=tasks,
            dependencies=dependencies,
            critical_path_ids=critical_path_ids,
            as_of=as_of,
        )
