import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.goal import Goal, GoalPriority
from app.db.models.plan import Plan, PlanItem, PlanStatus
from app.db.models.task import GoalDecomposition, Task, TaskDependency, TaskStatus
from app.db.models.user import User
from app.services.critical_path import CriticalPathService
from app.services.dependency_graph import DependencyGraphService
from app.services.goal import GoalService
from app.services.planning import PlanningService
from app.services.replanning.models import (
    PlanDiff,
    PriorityChangeItem,
    ReplanningDecision,
    ReplanningEvent,
    ReplanningReason,
    TaskRescheduleItem,
)

logger = logging.getLogger("lifethread.services.replanning")


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is timezone-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class AutonomousReplanningEngine:
    """Autonomous Replanning Engine for LifeThread.

    Detects constraint and execution changes, evaluates whether current plan remains valid,
    recalculates critical path and risks, generates versioned candidate plans, validates feasibility,
    computes explainable diffs, and commits updates with full provenance.
    """

    @classmethod
    async def process_event(
        cls,
        db: AsyncSession,
        event: ReplanningEvent,
        commit: bool = True,
    ) -> ReplanningDecision:
        """Execute the autonomous replanning pipeline for an incoming event.

        Pipeline:
        Current State
        → Detect Change
        → Impact Analysis
        → Identify Affected Tasks
        → Recalculate Critical Path
        → Recalculate Risk
        → Generate Candidate Plan
        → Validate Plan
        → Compare With Existing Plan
        → Commit New Plan (if commit=True)
        → Explain Changes
        """
        # 1. Retrieve Goal and verify ownership
        goal = await GoalService.get_goal_by_id(db=db, goal_id=event.goal_id, user_id=event.user_id)

        # 2. Retrieve Current Active Plan
        plan_q = (
            select(Plan)
            .where(Plan.goal_id == event.goal_id, Plan.status == PlanStatus.ACTIVE)
            .options(selectinload(Plan.items).selectinload(PlanItem.task))
            .order_by(Plan.version.desc())
        )
        plan_res = await db.execute(plan_q)
        current_plan = plan_res.scalars().first()

        # 3. Retrieve active decomposition version and all tasks
        decomp_q = (
            select(GoalDecomposition)
            .where(
                GoalDecomposition.goal_id == event.goal_id, GoalDecomposition.is_active.is_(True)
            )
            .order_by(GoalDecomposition.version.desc())
        )
        decomp_res = await db.execute(decomp_q)
        active_decomp = decomp_res.scalars().first()
        target_version = active_decomp.version if active_decomp else 1

        tasks_q = (
            select(Task)
            .where(Task.goal_id == event.goal_id, Task.version == target_version)
            .options(
                selectinload(Task.outgoing_dependencies),
                selectinload(Task.incoming_dependencies),
            )
        )
        tasks_res = await db.execute(tasks_q)
        tasks = list(tasks_res.scalars().all())

        task_ids = [t.id for t in tasks]
        task_map = {t.id: t for t in tasks}

        # Retrieve dependencies
        deps_q = select(TaskDependency).where(TaskDependency.task_id.in_(task_ids))
        deps_res = await db.execute(deps_q)
        dependencies = list(deps_res.scalars().all())
        edges = [(d.depends_on_task_id, d.task_id) for d in dependencies]

        # 4. Impact Analysis: Determine if replanning is necessary
        impact = cls._analyze_change_impact(
            goal=goal,
            current_plan=current_plan,
            tasks=tasks,
            edges=edges,
            event=event,
        )

        if not impact["replanning_required"]:
            # Current plan remains 100% valid; no new plan needed
            explanation = (
                f"No replanning required: {impact['rationale']}. "
                f"Existing Plan v{current_plan.version if current_plan else 1} remains valid and feasible."
            )
            return ReplanningDecision(
                goal_id=goal.id,
                user_id=goal.user_id,
                event=event,
                replanning_required=False,
                action_taken="NO_REPLANNING_NEEDED",
                previous_plan_version=current_plan.version if current_plan else None,
                new_plan_version=current_plan.version if current_plan else None,
                is_feasible=current_plan.is_feasible if current_plan else True,
                diff=None,
                impact_analysis=impact,
                explanation=explanation,
            )

        # 5. Apply event-specific adjustments to goal or tasks before candidate plan generation
        await cls._apply_event_modifications(
            db=db,
            goal=goal,
            tasks=tasks,
            task_map=task_map,
            event=event,
        )
        task_ids = [t.id for t in tasks]
        task_map = {t.id: t for t in tasks}

        # 6. Recalculate Critical Path
        try:
            topological_order = DependencyGraphService.topological_sort(task_ids, edges)
            new_critical_path_ids, _, _ = CriticalPathService.calculate_critical_path(
                tasks=tasks,
                dependencies=edges,
                topological_order=topological_order,
            )
        except Exception as e:
            logger.warning("Topological sort error during replanning: %s", e)
            topological_order = task_ids
            new_critical_path_ids = []

        new_cp_set = set(new_critical_path_ids)

        # 7. Resolve scheduling parameters
        user_res = await db.execute(select(User).where(User.id == event.user_id))
        user_obj = user_res.scalar_one_or_none()
        try:
            tz_str = user_obj.timezone if user_obj and user_obj.timezone else "UTC"
            user_tz = ZoneInfo(tz_str)
        except (ZoneInfoNotFoundError, ValueError):
            user_tz = ZoneInfo("UTC")

        # Scheduling preferences from event, current plan, or defaults
        daily_hours = float(
            event.details.get("daily_available_hours")
            or (
                current_plan.metadata_.get("daily_available_hours")
                if current_plan and current_plan.metadata_
                else 5.0
            )
            or 5.0
        )
        workdays_only = bool(
            event.details.get("workdays_only")
            if "workdays_only" in event.details
            else (
                current_plan.metadata_.get("workdays_only")
                if current_plan and current_plan.metadata_
                else True
            )
        )
        start_hour = int(
            event.details.get("daily_start_hour")
            or (
                current_plan.metadata_.get("daily_start_hour")
                if current_plan and current_plan.metadata_
                else 9
            )
            or 9
        )

        base_start = (
            current_plan.scheduled_start
            if (current_plan and current_plan.scheduled_start)
            else event.timestamp
        )
        plan_start = _ensure_utc(base_start)

        # 8. Generate Candidate Plan Schedule
        scheduled_items, plan_end, total_capacity_minutes = (
            PlanningService._schedule_tasks_calendar(
                tasks=tasks,
                task_map=task_map,
                edges=edges,
                topological_order=topological_order,
                critical_path_set=new_cp_set,
                plan_start=plan_start,
                user_tz=user_tz,
                daily_available_hours=daily_hours,
                workdays_only=workdays_only,
                daily_start_hour=start_hour,
            )
        )

        total_task_minutes = sum(t.estimated_minutes for t in tasks)

        # 9. Validate Candidate Plan & Feasibility
        is_feasible = True
        infeasibility_reasons: list[str] = []

        target_deadline = goal.deadline
        if event.reason == ReplanningReason.DEADLINE_CHANGED and "new_deadline" in event.details:
            raw_dl = event.details["new_deadline"]
            if isinstance(raw_dl, str):
                target_deadline = datetime.fromisoformat(raw_dl)
            elif isinstance(raw_dl, datetime):
                target_deadline = raw_dl

        if target_deadline is not None:
            dl_utc = _ensure_utc(target_deadline)
            pe_utc = _ensure_utc(plan_end)
            if pe_utc > dl_utc:
                is_feasible = False
                overrun_hours = round((pe_utc - dl_utc).total_seconds() / 3600, 1)
                infeasibility_reasons.append(
                    f"Scheduled finish ({pe_utc.strftime('%Y-%m-%d %H:%M UTC')}) exceeds target deadline "
                    f"({dl_utc.strftime('%Y-%m-%d %H:%M UTC')}) by {overrun_hours}h."
                )

        deadline_risk, risk_level = PlanningService._calculate_deadline_risk(
            plan_start=plan_start,
            plan_end=plan_end,
            deadline=target_deadline,
        )

        utilization = 0.0
        if total_capacity_minutes > 0:
            utilization = round(min(1.0, total_task_minutes / total_capacity_minutes), 3)

        # 10. Compare with Existing Plan & Generate PlanDiff
        max_v_q = select(func.max(Plan.version)).where(Plan.goal_id == event.goal_id)
        max_v_res = await db.execute(max_v_q)
        max_existing_v = max_v_res.scalar() or 0
        new_version = max_existing_v + 1

        diff = cls._build_plan_diff(
            old_plan=current_plan,
            new_version=new_version,
            scheduled_items=scheduled_items,
            new_critical_path_ids=new_critical_path_ids,
            new_risk_level=risk_level,
            new_plan_end=plan_end,
            is_feasible=is_feasible,
            infeasibility_reasons=infeasibility_reasons,
            event=event,
            daily_hours=daily_hours,
            target_deadline=target_deadline,
            task_map=task_map,
        )

        # 11. Commit New Plan if commit=True
        # IMPORTANT: Never silently replace previous plan - previous is marked SUPERSEDED
        if commit:
            # Mark existing active plans as SUPERSEDED
            if current_plan:
                current_plan.status = PlanStatus.SUPERSEDED

            new_plan_status = PlanStatus.ACTIVE if is_feasible else PlanStatus.INFEASIBLE
            plan_reason = f"Replanned: {diff.why_changed}"

            new_plan_model = Plan(
                goal_id=event.goal_id,
                version=new_version,
                status=new_plan_status,
                reason=plan_reason,
                is_feasible=is_feasible,
                deadline_risk=deadline_risk,
                risk_level=risk_level,
                schedule_utilization=utilization,
                total_duration_minutes=total_task_minutes,
                scheduled_start=plan_start,
                scheduled_end=plan_end,
                metadata_={
                    "daily_available_hours": daily_hours,
                    "workdays_only": workdays_only,
                    "daily_start_hour": start_hour,
                    "infeasibility_reasons": infeasibility_reasons,
                    "total_capacity_minutes": total_capacity_minutes,
                    "critical_path_ids": [str(uid) for uid in new_critical_path_ids],
                    "replanning_event_id": event.id,
                    "replanning_reason": event.reason.value,
                    "diff": diff.model_dump(mode="json"),
                },
            )
            db.add(new_plan_model)
            await db.flush()

            # Persist PlanItems
            for item_dict in scheduled_items:
                pi_start = item_dict.get("scheduled_start") or item_dict.get("start")
                pi_end = item_dict.get("scheduled_end") or item_dict.get("end")
                pi = PlanItem(
                    plan_id=new_plan_model.id,
                    task_id=item_dict["task_id"],
                    scheduled_start=pi_start,
                    scheduled_end=pi_end,
                    priority=item_dict["priority"],
                    rationale=item_dict.get("rationale", ""),
                )
                db.add(pi)

            await db.commit()

        action = "PLAN_COMMITTED" if commit else "PLAN_PREVIEWED"
        if not is_feasible:
            action = "PLAN_COMMITTED_INFEASIBLE" if commit else "PLAN_PREVIEWED_INFEASIBLE"

        decision_explanation = (
            f"Autonomous Replanning Decision: {action}. "
            f"Previous Plan v{current_plan.version if current_plan else 'none'} → New Plan v{new_version}. "
            f"Why changed: {diff.why_changed}. "
            f"What changed: {diff.what_changed}. "
            f"Feasibility: {diff.why_feasible}"
        )

        return ReplanningDecision(
            goal_id=goal.id,
            user_id=goal.user_id,
            event=event,
            replanning_required=True,
            action_taken=action,
            previous_plan_version=current_plan.version if current_plan else None,
            new_plan_version=new_version,
            is_feasible=is_feasible,
            diff=diff,
            impact_analysis=impact,
            explanation=decision_explanation,
        )

    @classmethod
    def _analyze_change_impact(
        cls,
        goal: Goal,
        current_plan: Plan | None,
        tasks: list[Task],
        edges: list[tuple[uuid.UUID, uuid.UUID]],
        event: ReplanningEvent,
    ) -> dict[str, Any]:
        """Analyze whether an event invalidates current plan schedule or feasibility."""
        if not current_plan or not current_plan.items:
            return {"replanning_required": True, "rationale": "No active plan currently exists"}

        reason = event.reason

        if reason == ReplanningReason.DEADLINE_CHANGED:
            new_dl = event.details.get("new_deadline")
            if not new_dl:
                return {"replanning_required": False, "rationale": "No new deadline provided"}

            new_dl_dt = datetime.fromisoformat(new_dl) if isinstance(new_dl, str) else new_dl
            new_dl_dt = _ensure_utc(new_dl_dt)

            curr_end = _ensure_utc(current_plan.scheduled_end) if current_plan else None

            # If deadline moved earlier and current plan completion date exceeds it -> replan!
            if curr_end and curr_end > new_dl_dt:
                return {
                    "replanning_required": True,
                    "rationale": f"Current plan finishes on {curr_end.strftime('%Y-%m-%d')}, exceeding new deadline {new_dl_dt.strftime('%Y-%m-%d')}",
                    "affected_dimension": "deadline_overrun",
                }
            # If deadline changed significantly, recalculate buffer and risk
            return {
                "replanning_required": True,
                "rationale": f"Goal deadline shifted to {new_dl_dt.strftime('%Y-%m-%d')}, altering risk profile",
                "affected_dimension": "deadline_buffer",
            }

        elif reason == ReplanningReason.AVAILABLE_TIME_CHANGED:
            new_hours = float(event.details.get("daily_available_hours", 0))
            old_hours = float(current_plan.metadata_.get("daily_available_hours", 5.0))
            if abs(new_hours - old_hours) >= 0.25:
                return {
                    "replanning_required": True,
                    "rationale": f"Available daily working capacity changed from {old_hours}h to {new_hours}h",
                    "affected_dimension": "capacity",
                }
            return {
                "replanning_required": False,
                "rationale": "Available time change was negligible",
            }

        elif reason == ReplanningReason.TASK_FAILED:
            failed_id = event.details.get("task_id")
            return {
                "replanning_required": True,
                "rationale": f"Task {failed_id or 'unknown'} failed execution, disrupting downstream milestones",
                "affected_dimension": "execution_failure",
            }

        elif reason == ReplanningReason.TASK_BLOCKED:
            blocked_id = event.details.get("task_id")
            return {
                "replanning_required": True,
                "rationale": f"Task {blocked_id or 'unknown'} entered BLOCKED state, delaying dependent tasks",
                "affected_dimension": "dependency_block",
            }

        elif reason == ReplanningReason.NEW_REQUIREMENT:
            return {
                "replanning_required": True,
                "rationale": f"New requirement introduced: {event.details.get('title', 'New Task')}",
                "affected_dimension": "scope_addition",
            }

        elif reason == ReplanningReason.PRIORITY_CHANGED:
            return {
                "replanning_required": True,
                "rationale": f"Task priority modified: {event.details.get('task_id', 'task')}",
                "affected_dimension": "priority_shift",
            }

        elif reason == ReplanningReason.DEPENDENCY_CHANGED:
            return {
                "replanning_required": True,
                "rationale": "Dependency graph topology altered",
                "affected_dimension": "dependency_graph",
            }

        elif reason == ReplanningReason.NEW_WEAKNESS_DISCOVERED:
            return {
                "replanning_required": True,
                "rationale": f"Evaluation identified critical weakness: {event.details.get('category', 'Weakness')}",
                "affected_dimension": "risk_mitigation",
            }

        return {"replanning_required": True, "rationale": event.description}

    @classmethod
    async def _apply_event_modifications(
        cls,
        db: AsyncSession,
        goal: Goal,
        tasks: list[Task],
        task_map: dict[uuid.UUID, Task],
        event: ReplanningEvent,
    ) -> None:
        """Apply in-memory or persisted changes corresponding to the trigger event."""
        reason = event.reason

        if reason == ReplanningReason.DEADLINE_CHANGED:
            raw_dl = event.details.get("new_deadline")
            if raw_dl:
                new_dl = datetime.fromisoformat(raw_dl) if isinstance(raw_dl, str) else raw_dl
                goal.deadline = new_dl
                await db.flush()

        elif reason == ReplanningReason.TASK_FAILED:
            failed_id = event.details.get("task_id")
            if failed_id:
                uid = (
                    uuid.UUID(str(failed_id)) if not isinstance(failed_id, uuid.UUID) else failed_id
                )
                if uid in task_map:
                    t = task_map[uid]
                    t.status = TaskStatus.BLOCKED
                    meta = getattr(t, "metadata_json", None) or getattr(t, "metadata", None) or {}
                    if not isinstance(meta, dict):
                        meta = {}
                    meta["failure_count"] = int(meta.get("failure_count", 0)) + 1
                    meta["last_execution_status"] = "FAILED"
                    meta["recent_error"] = event.details.get("error", "Execution failed")
                    if hasattr(t, "metadata_json"):
                        t.metadata_json = meta
                    await db.flush()

        elif reason == ReplanningReason.TASK_BLOCKED:
            blocked_id = event.details.get("task_id")
            if blocked_id:
                uid = (
                    uuid.UUID(str(blocked_id))
                    if not isinstance(blocked_id, uuid.UUID)
                    else blocked_id
                )
                if uid in task_map:
                    task_map[uid].status = TaskStatus.BLOCKED
                    await db.flush()

        elif reason == ReplanningReason.PRIORITY_CHANGED:
            t_id = event.details.get("task_id")
            new_p = event.details.get("new_priority")
            if t_id and new_p:
                uid = uuid.UUID(str(t_id)) if not isinstance(t_id, uuid.UUID) else t_id
                if uid in task_map:
                    task_map[uid].priority = GoalPriority(new_p)
                    await db.flush()

        elif reason == ReplanningReason.NEW_REQUIREMENT:
            # Create and add the new Task directly into decomposition
            title = event.details.get("title", "New Required Task")
            est = int(event.details.get("estimated_minutes", 60))
            p_val = event.details.get("priority", "HIGH")
            new_t = Task(
                goal_id=goal.id,
                title=title,
                status=TaskStatus.PENDING,
                priority=GoalPriority(p_val),
                estimated_minutes=est,
                version=tasks[0].version if tasks else 1,
            )
            db.add(new_t)
            await db.flush()
            tasks.append(new_t)
            task_map[new_t.id] = new_t

    @classmethod
    def _build_plan_diff(
        cls,
        old_plan: Plan | None,
        new_version: int,
        scheduled_items: list[dict[str, Any]],
        new_critical_path_ids: list[uuid.UUID],
        new_risk_level: str,
        new_plan_end: datetime,
        is_feasible: bool,
        infeasibility_reasons: list[str],
        event: ReplanningEvent,
        daily_hours: float,
        target_deadline: datetime | None,
        task_map: dict[uuid.UUID, Task] | None = None,
    ) -> PlanDiff:
        """Construct an explainable, structured PlanDiff comparing previous vs candidate plan."""
        old_items_map: dict[uuid.UUID, PlanItem] = {}
        old_version = None
        old_cp_ids: list[uuid.UUID] = []
        old_risk = "LOW"
        old_end = None

        if old_plan and old_plan.items:
            old_version = old_plan.version
            old_risk = old_plan.risk_level
            old_end = _ensure_utc(old_plan.scheduled_end)
            old_meta_cp = (
                old_plan.metadata_.get("critical_path_ids", []) if old_plan.metadata_ else []
            )
            old_cp_ids = [uuid.UUID(str(uid)) for uid in old_meta_cp]
            for pi in old_plan.items:
                old_items_map[pi.task_id] = pi

        new_items_map = {item["task_id"]: item for item in scheduled_items}

        tasks_added: list[dict[str, Any]] = []
        tasks_removed: list[dict[str, Any]] = []
        tasks_rescheduled: list[TaskRescheduleItem] = []
        priority_changes: list[PriorityChangeItem] = []
        tasks_unaffected: list[dict[str, Any]] = []

        # Detect additions & rescheduled
        for tid, n_item in new_items_map.items():
            n_start = _ensure_utc(n_item.get("scheduled_start") or n_item.get("start"))
            n_end = _ensure_utc(n_item.get("scheduled_end") or n_item.get("end"))
            t_title = (
                task_map[tid].title if task_map and tid in task_map else n_item.get("title", "Task")
            )

            if tid not in old_items_map:
                tasks_added.append(
                    {
                        "task_id": tid,
                        "title": t_title,
                        "priority": n_item["priority"],
                        "scheduled_start": n_start,
                        "scheduled_end": n_end,
                    }
                )
            else:
                o_pi = old_items_map[tid]
                o_start = _ensure_utc(o_pi.scheduled_start)
                o_end = _ensure_utc(o_pi.scheduled_end)
                n_prio = n_item["priority"]

                # Detect priority changes
                if o_pi.priority != n_prio:
                    priority_changes.append(
                        PriorityChangeItem(
                            task_id=tid,
                            title=t_title,
                            old_priority=o_pi.priority,
                            new_priority=n_prio,
                            rationale=f"Priority adjusted from {o_pi.priority.value} to {n_prio.value} following replan trigger {event.reason.value}",
                        )
                    )

                # Compare scheduled windows
                diff_sec = (n_start - o_start).total_seconds()
                shift_hours = round(diff_sec / 3600.0, 2)

                if abs(shift_hours) >= 0.1:
                    tasks_rescheduled.append(
                        TaskRescheduleItem(
                            task_id=tid,
                            title=t_title,
                            priority=n_item["priority"],
                            old_start=o_start,
                            new_start=n_start,
                            old_end=o_end,
                            new_end=n_end,
                            shift_hours=shift_hours,
                            rationale=n_item.get("rationale", ""),
                        )
                    )
                else:
                    tasks_unaffected.append(
                        {
                            "task_id": tid,
                            "title": t_title,
                        }
                    )

        # Detect removals
        for tid, o_pi in old_items_map.items():
            if tid not in new_items_map:
                tasks_removed.append(
                    {
                        "task_id": tid,
                        "title": o_pi.task.title if o_pi.task else "Task",
                    }
                )

        # Critical path comparison
        cp_changed = set(old_cp_ids) != set(new_critical_path_ids)

        # Rationale narratives
        why_changed = f"Plan revised due to {event.reason.value}: {event.description}"

        summary_parts: list[str] = []
        if tasks_added:
            added_titles = ", ".join(t["title"] for t in tasks_added)
            summary_parts.append(f"{len(tasks_added)} task(s) added ({added_titles})")
        if tasks_removed:
            removed_titles = ", ".join(t["title"] for t in tasks_removed)
            summary_parts.append(f"{len(tasks_removed)} task(s) removed ({removed_titles})")
        if tasks_rescheduled:
            rescheduled_titles = ", ".join(t.title for t in tasks_rescheduled)
            summary_parts.append(
                f"{len(tasks_rescheduled)} task(s) rescheduled ({rescheduled_titles})"
            )
        if priority_changes:
            prio_titles = ", ".join(f"{p.title} ({p.old_priority.value}→{p.new_priority.value})" for p in priority_changes)
            summary_parts.append(f"{len(priority_changes)} priority change(s) ({prio_titles})")
        if cp_changed and old_cp_ids:
            summary_parts.append("Critical path structure shifted")
        what_changed = (
            ", ".join(summary_parts)
            if summary_parts
            else "Schedule updated to adapt to current constraints."
        )

        # Why feasible narrative
        target_dl_utc = _ensure_utc(target_deadline)
        new_end_utc = _ensure_utc(new_plan_end)
        if is_feasible:
            if target_dl_utc:
                buffer_hours = round((target_dl_utc - new_end_utc).total_seconds() / 3600, 1)
                why_feasible = (
                    f"All {len(scheduled_items)} tasks fit comfortably within the target deadline "
                    f"({target_dl_utc.strftime('%Y-%m-%d %H:%M UTC')}) with {buffer_hours} hours buffer, "
                    f"allocating {daily_hours} daily available hours."
                )
            else:
                why_feasible = (
                    f"All {len(scheduled_items)} tasks are sequentially scheduled honoring all topological "
                    f"dependencies with {daily_hours} daily available hours."
                )
        else:
            why_feasible = (
                f"INFEASIBLE PLAN: {'; '.join(infeasibility_reasons)}. "
                f"Increasing daily hours or extending deadline is recommended."
            )

        return PlanDiff(
            old_plan_version=old_version,
            new_plan_version=new_version,
            why_changed=why_changed,
            what_changed=what_changed,
            tasks_added=tasks_added,
            tasks_removed=tasks_removed,
            tasks_rescheduled=tasks_rescheduled,
            priority_changes=priority_changes,
            tasks_unaffected=tasks_unaffected,
            critical_path_changed=cp_changed,
            old_critical_path_task_ids=old_cp_ids,
            new_critical_path_task_ids=new_critical_path_ids,
            old_risk_level=old_risk,
            new_risk_level=new_risk_level,
            old_completion_date=old_end,
            new_completion_date=new_plan_end,
            why_feasible=why_feasible,
        )
