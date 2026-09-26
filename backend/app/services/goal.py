import time
import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.goal import (
    Goal,
    GoalConstraint,
    GoalMilestone,
    GoalStatus,
)
from app.schemas.goal import GoalCreate, GoalUpdate


class GoalService:
    """Domain service managing Goal persistence, state transitions, and user isolation."""

    _query_cache: dict[str, tuple[float, tuple[Sequence[Goal], int]]] = {}
    _cache_ttl_seconds: float = 30.0

    @classmethod
    def invalidate_user_cache(cls, user_id: uuid.UUID) -> None:
        """Evict all cached query results for the specified user."""
        prefix = f"{user_id}:"
        keys_to_delete = [k for k in cls._query_cache if k.startswith(prefix)]
        for k in keys_to_delete:
            cls._query_cache.pop(k, None)

    @classmethod
    async def create_goal(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        goal_in: GoalCreate,
    ) -> Goal:
        """Create a new goal along with its optional constraints and milestones."""
        goal = Goal(
            user_id=user_id,
            title=goal_in.title,
            objective=goal_in.objective,
            description=goal_in.description,
            status=GoalStatus.ACTIVE,
            priority=goal_in.priority,
            deadline=goal_in.deadline,
            success_criteria=goal_in.success_criteria,
        )

        for c in goal_in.constraints:
            constraint = GoalConstraint(
                type=c.type,
                value=c.value,
                metadata_=c.metadata,
            )
            goal.constraints.append(constraint)

        for m in goal_in.milestones:
            milestone = GoalMilestone(
                title=m.title,
                description=m.description,
                status=m.status,
                order_index=m.order_index,
                deadline=m.deadline,
            )
            goal.milestones.append(milestone)

        db.add(goal)
        await db.flush()
        await db.refresh(goal)
        cls.invalidate_user_cache(user_id)
        return goal

    @staticmethod
    async def get_goal_by_id(
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Goal:
        """Retrieve a single goal ensuring it belongs to the authenticated user.

        Detects and audit logs any IDOR attempt if the goal belongs to another tenant.

        Raises:
            HTTPException: 404 if goal does not exist or belongs to another user.
        """
        from app.db.access_control import DatabaseAccessControl

        return await DatabaseAccessControl.get_user_resource_or_404(
            db=db,
            model=Goal,
            resource_id=goal_id,
            user_id=user_id,
            resource_name="goal",
        )

    @classmethod
    async def list_goals(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        status_filter: GoalStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Goal], int]:
        """List goals belonging to the user with optional status filter, pagination, and caching."""
        cache_key = f"{user_id}:{status_filter}:{limit}:{offset}"
        now = time.time()
        if cache_key in cls._query_cache:
            ts, cached_res = cls._query_cache[cache_key]
            if now - ts < cls._cache_ttl_seconds:
                return cached_res

        query = select(Goal).where(Goal.user_id == user_id)
        count_query = select(func.count()).select_from(Goal).where(Goal.user_id == user_id)

        if status_filter is not None:
            query = query.where(Goal.status == status_filter)
            count_query = count_query.where(Goal.status == status_filter)

        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(Goal.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        items = result.scalars().all()

        cls._query_cache[cache_key] = (now, (items, total))
        return items, total

    @classmethod
    async def update_goal(
        cls,
        db: AsyncSession,
        goal: Goal,
        goal_in: GoalUpdate,
    ) -> Goal:
        """Update fields on an existing goal."""
        update_data = goal_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(goal, field, value)

        await db.flush()
        await db.refresh(goal)
        cls.invalidate_user_cache(goal.user_id)
        return goal

    @classmethod
    async def pause_goal(cls, db: AsyncSession, goal: Goal) -> Goal:
        """Pause an active goal."""
        if goal.status == GoalStatus.PAUSED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Goal is already paused",
            )

        if goal.status != GoalStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot pause goal in {goal.status.value} status; must be ACTIVE",
            )

        goal.status = GoalStatus.PAUSED
        await db.flush()
        await db.refresh(goal)
        cls.invalidate_user_cache(goal.user_id)
        return goal

    @classmethod
    async def resume_goal(cls, db: AsyncSession, goal: Goal) -> Goal:
        """Resume a paused or draft goal back to ACTIVE status."""
        if goal.status == GoalStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Goal is already active",
            )

        if goal.status not in [GoalStatus.PAUSED, GoalStatus.DRAFT]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot resume goal in {goal.status.value} status; must be PAUSED or DRAFT",
            )

        goal.status = GoalStatus.ACTIVE
        await db.flush()
        await db.refresh(goal)
        cls.invalidate_user_cache(goal.user_id)
        return goal

    @classmethod
    async def complete_goal(cls, db: AsyncSession, goal: Goal) -> Goal:
        """Transition an active or paused goal to COMPLETED."""
        if goal.status == GoalStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Goal is already completed",
            )

        if goal.status not in [GoalStatus.ACTIVE, GoalStatus.PAUSED]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot complete goal in {goal.status.value} status; must be ACTIVE or PAUSED",
            )

        goal.status = GoalStatus.COMPLETED
        await db.flush()
        await db.refresh(goal)
        cls.invalidate_user_cache(goal.user_id)
        return goal

    @classmethod
    async def delete_goal(cls, db: AsyncSession, goal: Goal) -> None:
        """Delete a goal and cascade removal to its constraints and milestones."""
        user_id = goal.user_id
        await db.delete(goal)
        await db.flush()
        cls.invalidate_user_cache(user_id)
