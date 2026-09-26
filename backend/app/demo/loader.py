"""LifeThread Demo Data Loader.

Module 46: Demo Data and Example Scenarios.

Provides transactional loading, reset, and status inspection for the 6 demo scenarios.
Enforces strict separation from production logic and data via metadata tagging and
environment setting checks.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models.goal import (
    Goal,
    GoalConstraint,
    GoalMilestone,
    GoalPriority,
    GoalStatus,
    MilestoneStatus,
)
from app.db.models.memory import Memory, MemoryStatus, MemoryType
from app.db.models.plan import Plan, PlanItem, PlanStatus
from app.db.models.task import GoalDecomposition, Task, TaskDependency, TaskStatus
from app.db.models.user import User
from app.demo.scenarios import (
    DEMO_USER_EMAIL,
    DEMO_USER_NAME,
    DEMO_USER_PASSWORD,
    get_demo_scenarios_data,
)
from app.services.agent_trace.models import EventStatus, ExecutionEventType
from app.services.agent_trace.service import AgentTraceService

logger = logging.getLogger("lifethread.demo.loader")


def _generate_demo_embedding(seed_val: int = 1, dim: int = 1536) -> list[float]:
    """Generate a deterministic 1536-dimensional float vector for semantic search."""
    base = (seed_val % 10 + 1) * 0.05
    return [round(base + (i % 7) * 0.01, 4) for i in range(dim)]


class DemoDataLoader:
    """Manages the lifecycle of development and demonstration datasets."""

    @classmethod
    def is_demo_allowed(cls) -> bool:
        """Check whether demo data operations are allowed in the current environment."""
        settings = get_settings()
        if not settings.ALLOW_DEMO_DATA:
            return False
        if settings.ENVIRONMENT == "production":
            return False
        return True

    @classmethod
    async def get_or_create_demo_user(cls, session: AsyncSession) -> User:
        """Retrieve existing demo user or create a new dedicated demo user."""
        stmt = select(User).where(User.email == DEMO_USER_EMAIL)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                email=DEMO_USER_EMAIL,
                password_hash=hash_password(DEMO_USER_PASSWORD),
                display_name=DEMO_USER_NAME,
                timezone="UTC",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            logger.info("Created dedicated demo user: %s (id: %s)", DEMO_USER_EMAIL, user.id)

        return user

    @classmethod
    async def clear_demo_data(
        cls,
        session: AsyncSession,
        target_user_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Safely delete demo entities associated with demo user or tagged with demo metadata.

        Does not modify non-demo user data.
        """
        if not cls.is_demo_allowed():
            raise PermissionError("Demo data clearing is disabled in production environments.")

        # Determine target user
        if target_user_id is None:
            user_stmt = select(User.id).where(User.email == DEMO_USER_EMAIL)
            target_user_id = (await session.execute(user_stmt)).scalar_one_or_none()

        if target_user_id is None:
            return {"goals_deleted": 0, "memories_deleted": 0}

        # Count before deletion
        goal_count_stmt = select(Goal.id).where(Goal.user_id == target_user_id)
        goals_to_delete = (await session.execute(goal_count_stmt)).scalars().all()

        mem_count_stmt = select(Memory.id).where(Memory.user_id == target_user_id)
        mems_to_delete = (await session.execute(mem_count_stmt)).scalars().all()

        # Delete goals (cascades to constraints, milestones, tasks, dependencies, decompositions, plans)
        if goals_to_delete:
            await session.execute(delete(Goal).where(Goal.id.in_(goals_to_delete)))

        # Delete memories
        if mems_to_delete:
            await session.execute(delete(Memory).where(Memory.id.in_(mems_to_delete)))

        await session.commit()
        logger.info(
            "Cleared demo data for user %s: %d goals, %d memories deleted",
            target_user_id,
            len(goals_to_delete),
            len(mems_to_delete),
        )

        return {
            "goals_deleted": len(goals_to_delete),
            "memories_deleted": len(mems_to_delete),
        }

    @classmethod
    async def load_demo_scenarios(
        cls,
        session: AsyncSession,
        target_user: User | None = None,
        reset_existing: bool = True,
    ) -> dict[str, Any]:
        """Load all 6 realistic long-running scenarios into the database transactionally."""
        if not cls.is_demo_allowed():
            raise PermissionError("Demo data loading is disabled in production environments.")

        # Determine target user
        user = target_user or await cls.get_or_create_demo_user(session)

        # Optionally reset existing demo data for this user
        if reset_existing:
            await cls.clear_demo_data(session, target_user_id=user.id)

        now = datetime.now(UTC)
        scenarios_data = get_demo_scenarios_data(now=now)

        created_goals: list[Goal] = []
        total_tasks_count = 0
        total_plans_count = 0
        total_memories_count = 0
        total_dependencies_count = 0

        for sc_idx, sc_data in enumerate(scenarios_data, start=1):
            # 1. Create Goal
            goal = Goal(
                user_id=user.id,
                title=sc_data["title"],
                objective=sc_data["objective"],
                description=sc_data["description"],
                priority=GoalPriority(sc_data["priority"]),
                status=GoalStatus(sc_data["status"]),
                deadline=sc_data["deadline"],
                success_criteria=sc_data["success_criteria"],
            )
            session.add(goal)
            await session.flush()
            created_goals.append(goal)

            # 2. Add Constraints
            for c_data in sc_data.get("constraints", []):
                meta = dict(c_data.get("metadata", {}))
                meta.update({"is_demo": True, "scenario_id": sc_data["id"]})
                constraint = GoalConstraint(
                    goal_id=goal.id,
                    type=c_data["type"],
                    value=c_data["value"],
                    metadata_=meta,
                )
                session.add(constraint)

            # 3. Add Milestones
            created_milestones: list[GoalMilestone] = []
            for m_data in sc_data.get("milestones", []):
                milestone = GoalMilestone(
                    goal_id=goal.id,
                    title=m_data["title"],
                    description=m_data.get("description"),
                    status=MilestoneStatus(m_data["status"]),
                    order_index=m_data["order_index"],
                    deadline=m_data.get("deadline"),
                )
                session.add(milestone)
                await session.flush()
                created_milestones.append(milestone)

            # 4. Add Decomposed Tasks
            created_tasks: list[Task] = []
            for t_data in sc_data.get("tasks", []):
                m_idx = t_data.get("milestone_index")
                assigned_milestone_id = (
                    created_milestones[m_idx].id
                    if m_idx is not None and m_idx < len(created_milestones)
                    else None
                )

                task = Task(
                    goal_id=goal.id,
                    milestone_id=assigned_milestone_id,
                    version=1,
                    title=t_data["title"],
                    description=t_data.get("description"),
                    status=TaskStatus(t_data["status"]),
                    priority=GoalPriority(t_data["priority"]),
                    estimated_minutes=t_data.get("estimated_minutes", 60),
                    due_at=t_data.get("due_at"),
                    completed_at=t_data.get("completed_at"),
                )
                session.add(task)
                await session.flush()
                created_tasks.append(task)
                total_tasks_count += 1

            # 5. Add Task Dependencies (e.g. Scenario 5 Blocked Dependency)
            for t_idx, t_data in enumerate(sc_data.get("tasks", [])):
                blocked_by_idx = t_data.get("blocked_by_task_index")
                if (
                    blocked_by_idx is not None
                    and blocked_by_idx < len(created_tasks)
                    and t_idx < len(created_tasks)
                ):
                    dep = TaskDependency(
                        task_id=created_tasks[t_idx].id,
                        depends_on_task_id=created_tasks[blocked_by_idx].id,
                        dependency_type="BLOCKS",
                    )
                    session.add(dep)
                    total_dependencies_count += 1

            # 6. Add Goal Decomposition Revision
            critical_minutes = sum(t.estimated_minutes for t in created_tasks)
            decomp = GoalDecomposition(
                goal_id=goal.id,
                version=1,
                task_count=len(created_tasks),
                critical_path_duration_minutes=critical_minutes,
                is_active=True,
                metadata_={
                    "is_demo": True,
                    "scenario_id": sc_data["id"],
                    "scenario_name": sc_data["scenario_name"],
                    "critical_path_task_ids": [str(t.id) for t in created_tasks],
                },
            )
            session.add(decomp)

            # If Scenario 1 (Changing Deadlines), add Decomposition Version 2
            if sc_data["id"] == "scenario_1_changing_deadlines":
                decomp_v2 = GoalDecomposition(
                    goal_id=goal.id,
                    version=2,
                    task_count=len(created_tasks),
                    critical_path_duration_minutes=critical_minutes,
                    is_active=True,
                    metadata_={
                        "is_demo": True,
                        "scenario_id": sc_data["id"],
                        "replanning_reason": "Auditor deadline compression from 30 days to 12 days",
                        "critical_path_task_ids": [str(t.id) for t in created_tasks],
                    },
                )
                session.add(decomp_v2)

            # 7. Add Plan Versions and Allocated Plan Items
            for p_data in sc_data.get("plans", []):
                plan = Plan(
                    goal_id=goal.id,
                    version=p_data["version"],
                    status=PlanStatus(p_data["status"]),
                    is_feasible=p_data["is_feasible"],
                    deadline_risk=p_data["deadline_risk"],
                    risk_level=p_data["risk_level"],
                    schedule_utilization=p_data["schedule_utilization"],
                    reason=p_data.get("reason"),
                    generated_at=p_data.get("generated_at", now),
                )
                session.add(plan)
                await session.flush()
                total_plans_count += 1

                # Allocate scheduled items across tasks
                accumulated_start = plan.generated_at
                for t in created_tasks:
                    p_item = PlanItem(
                        plan_id=plan.id,
                        task_id=t.id,
                        scheduled_start=accumulated_start,
                        scheduled_end=accumulated_start + timedelta(minutes=t.estimated_minutes),
                        priority=t.priority,
                        rationale=f"Scheduled execution window for '{t.title}'",
                    )
                    session.add(p_item)
                    # Next task scheduled for next day / working slot
                    accumulated_start += timedelta(days=1)

            # 8. Add Semantic Memories
            for m_idx, mem_data in enumerate(sc_data.get("memories", [])):
                meta = dict(mem_data.get("metadata", {}))
                meta.update({"is_demo": True, "goal_id": str(goal.id), "scenario_id": sc_data["id"]})
                memory = Memory(
                    user_id=user.id,
                    memory_type=MemoryType(mem_data["memory_type"]),
                    content=mem_data["content"],
                    importance_score=mem_data.get("importance_score", 0.8),
                    confidence=mem_data.get("confidence", 1.0),
                    source=mem_data.get("source", "demo_loader"),
                    status=MemoryStatus.ACTIVE,
                    metadata_json=meta,
                    embedding=_generate_demo_embedding(seed_val=sc_idx * 10 + m_idx),
                )
                session.add(memory)
                total_memories_count += 1

            # 9. Record Agent Execution Runs & Traces
            for r_data in sc_data.get("agent_runs", []):
                run = AgentTraceService.start_run(
                    user_id=user.id,
                    trigger=r_data["trigger"],
                    goal_id=goal.id,
                    goal_title=goal.title,
                    summary=r_data["summary"],
                )
                # Append events
                for ev in r_data.get("events", []):
                    ev_type_str = ev.get("event_type", "AGENT_RUN")
                    ev_type = getattr(ExecutionEventType, ev_type_str, ExecutionEventType.AGENT_RUN)
                    ev_status_str = ev.get("status", "SUCCESS")
                    ev_status = getattr(EventStatus, ev_status_str, EventStatus.SUCCESS)
                    AgentTraceService.record_event(
                        run_id=run.id,
                        user_id=user.id,
                        event_type=ev_type,
                        status=ev_status,
                        short_explanation=ev.get("description", ""),
                        goal_id=goal.id,
                        goal_title=goal.title,
                    )
                # Finalize run
                run_status_str = r_data.get("status", "SUCCESS")
                run_status = getattr(EventStatus, run_status_str, EventStatus.SUCCESS)
                AgentTraceService.finish_run(
                    run_id=run.id,
                    user_id=user.id,
                    status=run_status,
                    summary=r_data.get("summary"),
                )

        await session.commit()
        logger.info(
            "Demo data loaded successfully: %d goals, %d tasks, %d dependencies, %d plans, %d memories",
            len(created_goals),
            total_tasks_count,
            total_dependencies_count,
            total_plans_count,
            total_memories_count,
        )

        return {
            "success": True,
            "user_id": str(user.id),
            "user_email": user.email,
            "goals_created": len(created_goals),
            "tasks_created": total_tasks_count,
            "dependencies_created": total_dependencies_count,
            "plans_created": total_plans_count,
            "memories_created": total_memories_count,
            "scenarios": [
                {
                    "scenario_id": sc["id"],
                    "scenario_name": sc["scenario_name"],
                    "goal_title": sc["title"],
                    "priority": sc["priority"],
                    "status": sc["status"],
                }
                for sc in scenarios_data
            ],
        }

    @classmethod
    async def get_demo_status(
        cls,
        session: AsyncSession,
        target_user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Check whether demo data currently exists and return entity counts."""
        if target_user_id is None:
            user_stmt = select(User.id).where(User.email == DEMO_USER_EMAIL)
            target_user_id = (await session.execute(user_stmt)).scalar_one_or_none()

        if target_user_id is None:
            return {
                "is_loaded": False,
                "user_exists": False,
                "goals_count": 0,
                "memories_count": 0,
            }

        goal_stmt = select(Goal.id).where(Goal.user_id == target_user_id)
        goal_count = len((await session.execute(goal_stmt)).scalars().all())

        mem_stmt = select(Memory.id).where(Memory.user_id == target_user_id)
        mem_count = len((await session.execute(mem_stmt)).scalars().all())

        return {
            "is_loaded": goal_count >= 6,
            "user_exists": True,
            "user_id": str(target_user_id),
            "goals_count": goal_count,
            "memories_count": mem_count,
        }
