import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.goal import GoalStatus
from app.db.models.task import TaskStatus
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.dependencies.llm import get_llm_provider_dep
from app.schemas.decomposition import (
    DecompositionRequest,
    GoalDecompositionResponse,
    TaskDependencyGraphResponse,
    TaskListResponse,
    TaskResponse,
    TaskUpdate,
)
from app.schemas.goal import (
    GoalCreate,
    GoalListResponse,
    GoalResponse,
    GoalUpdate,
)
from app.schemas.goal_understanding import GoalUnderstandingSchema, GoalUnderstandRequest
from app.schemas.plan import PlanCreateRequest, PlanListResponse, PlanResponse
from app.services.decomposition import DecompositionService
from app.services.goal import GoalService
from app.services.goal_evaluation import GoalEvaluation, GoalEvaluationEngine
from app.services.goal_understanding import GoalUnderstandingService
from app.services.llm import BaseLLMProvider
from app.services.planning import PlanningService
from app.services.replanning import (
    AutonomousReplanningEngine,
    PlanComparisonSummary,
    PlanDiff,
    PriorityChangeItem,
    ReplanningDecision,
    ReplanningDiffResponse,
    ReplanningEvent,
    ReplanningReason,
)

logger = logging.getLogger("lifethread.goals")
router = APIRouter(prefix="/goals", tags=["Goal Engine"])


@router.post(
    "/understand",
    response_model=GoalUnderstandingSchema,
    status_code=status.HTTP_200_OK,
    summary="Understand Natural Language Goal",
    description=(
        "Interpret a natural language goal description into a structured, validated specification. "
        "Does NOT automatically persist the final goal until explicitly confirmed."
    ),
)
async def understand_goal(
    payload: GoalUnderstandRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    llm_provider: Annotated[BaseLLMProvider, Depends(get_llm_provider_dep)],
) -> GoalUnderstandingSchema:
    """Analyze and extract structured goal specifications from natural language."""
    user_tz = payload.timezone or current_user.timezone or "UTC"
    result = await GoalUnderstandingService.understand_goal(
        raw_text=payload.text,
        user_timezone=user_tz,
        reference_time=payload.reference_time,
        clarification_answers=payload.clarification_answers,
        llm_provider=llm_provider,
    )
    logger.info(
        "Analyzed natural language goal",
        extra={
            "user_id": str(current_user.id),
            "is_ambiguous": result.is_ambiguous,
            "has_deadline": result.deadline is not None,
        },
    )
    return result


@router.post(
    "",
    response_model=GoalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Goal",
    description="Create a new long-running goal with optional constraints and milestones.",
)
async def create_goal(
    goal_in: GoalCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GoalResponse:
    """Create a new goal belonging to the authenticated user."""
    goal = await GoalService.create_goal(db=db, user_id=current_user.id, goal_in=goal_in)
    logger.info(
        "Created goal",
        extra={"goal_id": str(goal.id), "user_id": str(current_user.id), "title": goal.title},
    )
    return GoalResponse.model_validate(goal)


@router.get(
    "",
    response_model=GoalListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Goals",
    description="Retrieve a paginated collection of goals belonging to the authenticated user.",
)
async def list_goals(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[
        GoalStatus | None,
        Query(alias="status", description="Filter by status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Items to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Pagination offset")] = 0,
) -> GoalListResponse:
    """List goals owned by the authenticated user."""
    items, total = await GoalService.list_goals(
        db=db,
        user_id=current_user.id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return GoalListResponse(
        items=[GoalResponse.model_validate(g) for g in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{goal_id}",
    response_model=GoalResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Goal",
    description="Retrieve details, constraints, and milestones for a specific goal.",
)
async def get_goal(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GoalResponse:
    """Retrieve a goal ensuring ownership."""
    goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=current_user.id)
    return GoalResponse.model_validate(goal)


@router.patch(
    "/{goal_id}",
    response_model=GoalResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Goal",
    description="Update mutable attributes of an existing goal.",
)
async def update_goal(
    goal_id: uuid.UUID,
    goal_in: GoalUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GoalResponse:
    """Update goal fields ensuring user ownership."""
    goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=current_user.id)
    updated = await GoalService.update_goal(db=db, goal=goal, goal_in=goal_in)
    logger.info("Updated goal", extra={"goal_id": str(goal.id), "user_id": str(current_user.id)})
    return GoalResponse.model_validate(updated)


@router.post(
    "/{goal_id}/pause",
    response_model=GoalResponse,
    status_code=status.HTTP_200_OK,
    summary="Pause Goal",
    description="Pause an active goal, freezing further automatic progress.",
)
async def pause_goal(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GoalResponse:
    """Pause an active goal."""
    goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=current_user.id)
    paused = await GoalService.pause_goal(db=db, goal=goal)
    logger.info("Paused goal", extra={"goal_id": str(goal.id), "user_id": str(current_user.id)})
    return GoalResponse.model_validate(paused)


@router.post(
    "/{goal_id}/resume",
    response_model=GoalResponse,
    status_code=status.HTTP_200_OK,
    summary="Resume Goal",
    description="Resume a paused goal back to active state.",
)
async def resume_goal(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GoalResponse:
    """Resume a paused goal."""
    goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=current_user.id)
    resumed = await GoalService.resume_goal(db=db, goal=goal)
    logger.info("Resumed goal", extra={"goal_id": str(goal.id), "user_id": str(current_user.id)})
    return GoalResponse.model_validate(resumed)


@router.post(
    "/{goal_id}/complete",
    response_model=GoalResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete Goal",
    description="Mark a goal as successfully completed.",
)
async def complete_goal(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GoalResponse:
    """Transition goal to completed status."""
    goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=current_user.id)
    completed = await GoalService.complete_goal(db=db, goal=goal)
    logger.info("Completed goal", extra={"goal_id": str(goal.id), "user_id": str(current_user.id)})
    return GoalResponse.model_validate(completed)


@router.delete(
    "/{goal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Goal",
    description="Permanently delete a goal and its associated constraints and milestones.",
)
async def delete_goal(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete goal ensuring ownership."""
    goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=current_user.id)
    await GoalService.delete_goal(db=db, goal=goal)
    logger.info("Deleted goal", extra={"goal_id": str(goal_id), "user_id": str(current_user.id)})


@router.post(
    "/{goal_id}/decompose",
    response_model=GoalDecompositionResponse,
    status_code=status.HTTP_200_OK,
    summary="Decompose Goal",
    description="Decompose a goal into progressive milestones, actionable tasks, and a validated dependency DAG.",
)
async def decompose_goal(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm_provider: Annotated[BaseLLMProvider, Depends(get_llm_provider_dep)],
    payload: DecompositionRequest | None = None,
) -> GoalDecompositionResponse:
    """Trigger goal decomposition into versioned tasks and dependencies."""
    request_data = payload or DecompositionRequest()
    return await DecompositionService.decompose_goal(
        db=db,
        goal_id=goal_id,
        user_id=current_user.id,
        request=request_data,
        llm_provider=llm_provider,
    )


@router.get(
    "/{goal_id}/tasks",
    response_model=TaskListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Goal Tasks",
    description="Retrieve tasks generated for a goal with optional version and status filtering.",
)
async def get_goal_tasks(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    version: Annotated[
        int | None, Query(description="Decomposition version number (defaults to active)")
    ] = None,
    status_filter: Annotated[
        TaskStatus | None, Query(alias="status", description="Filter by task status")
    ] = None,
) -> TaskListResponse:
    """List tasks for a goal revision."""
    return await DecompositionService.list_goal_tasks(
        db=db,
        goal_id=goal_id,
        user_id=current_user.id,
        version=version,
        status_filter=status_filter,
    )


@router.patch(
    "/{goal_id}/tasks/{task_id}",
    response_model=TaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Goal Task",
    description="Update mutable attributes of an execution task.",
)
async def update_goal_task(
    goal_id: uuid.UUID,
    task_id: uuid.UUID,
    task_in: TaskUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskResponse:
    """Update goal task ensuring tenant ownership."""
    updated = await DecompositionService.update_task(
        db=db,
        goal_id=goal_id,
        task_id=task_id,
        user_id=current_user.id,
        task_in=task_in,
    )
    return TaskResponse.model_validate(updated)


@router.post(
    "/{goal_id}/tasks/{task_id}/complete",
    response_model=TaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete Goal Task",
    description="Mark an individual goal task as completed.",
)
async def complete_goal_task(
    goal_id: uuid.UUID,
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskResponse:
    """Complete goal task ensuring tenant ownership."""
    completed = await DecompositionService.complete_task(
        db=db,
        goal_id=goal_id,
        task_id=task_id,
        user_id=current_user.id,
    )
    return TaskResponse.model_validate(completed)


@router.get(
    "/{goal_id}/dependencies",
    response_model=TaskDependencyGraphResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Goal Dependencies Graph",
    description="Retrieve the complete directed dependency graph, critical path, and topological order for a goal.",
)
async def get_goal_dependencies(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    version: Annotated[
        int | None, Query(description="Decomposition version number (defaults to active)")
    ] = None,
) -> TaskDependencyGraphResponse:
    """Retrieve dependency graph and critical path for a goal."""
    return await DecompositionService.get_goal_dependencies(
        db=db,
        goal_id=goal_id,
        user_id=current_user.id,
        version=version,
    )


@router.post(
    "/{goal_id}/plan",
    response_model=PlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate Goal Execution Plan",
    description="Generate a realistic, deterministic schedule allocating tasks across available user hours.",
)
async def generate_goal_plan(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: PlanCreateRequest | None = None,
) -> PlanResponse:
    """Generate a versioned schedule for a goal."""
    request_data = payload or PlanCreateRequest()
    return await PlanningService.generate_plan(
        db=db,
        goal_id=goal_id,
        user_id=current_user.id,
        request=request_data,
    )


@router.get(
    "/{goal_id}/plan",
    response_model=PlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Active Goal Plan",
    description="Retrieve the latest active schedule and plan items for a goal.",
)
async def get_active_goal_plan(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlanResponse:
    """Retrieve active plan for a goal."""
    return await PlanningService.get_active_plan(
        db=db,
        goal_id=goal_id,
        user_id=current_user.id,
    )


@router.get(
    "/{goal_id}/plans",
    response_model=PlanListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Historical Goal Plans",
    description="Retrieve revision history of generated schedules for a goal.",
)
async def list_goal_plans(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlanListResponse:
    """List all plan versions for a goal."""
    return await PlanningService.list_plans(
        db=db,
        goal_id=goal_id,
        user_id=current_user.id,
    )


@router.get(
    "/{goal_id}/plans/{version}",
    response_model=PlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Specific Goal Plan Version",
    description="Retrieve details of a specific historical plan version.",
)
async def get_goal_plan_version(
    goal_id: uuid.UUID,
    version: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlanResponse:
    """Retrieve historical plan revision by version number."""
    return await PlanningService.get_plan_by_version(
        db=db,
        goal_id=goal_id,
        user_id=current_user.id,
        version=version,
    )


@router.post(
    "/{goal_id}/evaluate",
    response_model=GoalEvaluation,
    status_code=status.HTTP_200_OK,
    summary="Evaluate Goal Plan Progress & Risk",
    description="Run advanced evaluation over goal execution state, weighted progress, performance, consistency, and risk factors.",
)
async def evaluate_goal(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GoalEvaluation:
    """Evaluate whether the user's current plan is actually moving the goal forward."""
    return await GoalEvaluationEngine.evaluate_goal(
        db=db,
        goal_id=goal_id,
        user_id=current_user.id,
    )


class ReplanRequest(BaseModel):
    """Payload to trigger autonomous replanning for a goal."""

    reason: ReplanningReason
    description: str
    details: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/{goal_id}/replan",
    response_model=ReplanningDecision,
    status_code=status.HTTP_200_OK,
    summary="Trigger Autonomous Replanning",
    description="Analyze a constraint or execution change, determine plan validity, generate a new versioned plan, and commit it with an explainable diff.",
)
async def replan_goal(
    goal_id: uuid.UUID,
    payload: ReplanRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReplanningDecision:
    """Execute autonomous replanning pipeline and commit new versioned plan."""
    event = ReplanningEvent(
        goal_id=goal_id,
        user_id=current_user.id,
        reason=payload.reason,
        description=payload.description,
        details=payload.details,
    )
    return await AutonomousReplanningEngine.process_event(
        db=db,
        event=event,
        commit=True,
    )


@router.post(
    "/{goal_id}/replan/preview",
    response_model=ReplanningDecision,
    status_code=status.HTTP_200_OK,
    summary="Preview Autonomous Replanning",
    description="Preview proposed replanning changes and explainable diff without committing to the database.",
)
async def preview_replan_goal(
    goal_id: uuid.UUID,
    payload: ReplanRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReplanningDecision:
    """Preview candidate replan and diff without committing."""
    event = ReplanningEvent(
        goal_id=goal_id,
        user_id=current_user.id,
        reason=payload.reason,
        description=payload.description,
        details=payload.details,
    )
    return await AutonomousReplanningEngine.process_event(
        db=db,
        event=event,
        commit=False,
    )


@router.get(
    "/{goal_id}/replanning-diff",
    response_model=ReplanningDiffResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Replanning Diff and Visualization",
    description="Retrieve explainable diff between plan versions showing reason, previous plan, new plan, added/removed/rescheduled tasks, priority changes, and concise user-facing explanation without exposing private CoT.",
)
async def get_replanning_diff(
    goal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    version_a: Annotated[int | None, Query(description="Base plan version to compare from")] = None,
    version_b: Annotated[int | None, Query(description="Target plan version to compare to")] = None,
) -> ReplanningDiffResponse:
    """Retrieve visual plan diff between two historical or active plan revisions."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models.plan import Plan, PlanItem
    from app.services.replanning.models import TaskRescheduleItem

    # 1. Verify goal ownership
    _goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=current_user.id)

    # 2. Query all plans for this goal
    q = (
        select(Plan)
        .where(Plan.goal_id == goal_id)
        .options(selectinload(Plan.items).selectinload(PlanItem.task))
        .order_by(Plan.version.asc())
    )
    res = await db.execute(q)
    all_plans = res.scalars().all()

    if not all_plans:
        return ReplanningDiffResponse(
            plan_changed=False,
            status_label="NO PLAN",
            reason="No plan generated yet",
            why_explanation="This goal has not generated an operational schedule yet.",
            why_feasible="Generate an initial plan from the goal workspace.",
        )

    # Helper to build PlanComparisonSummary
    def summarize_plan(p: Plan) -> PlanComparisonSummary:
        items_payload = [
            {
                "task_id": str(pi.task_id),
                "title": pi.task.title if pi.task else "Task",
                "scheduled_start": pi.scheduled_start.isoformat(),
                "scheduled_end": pi.scheduled_end.isoformat(),
                "priority": pi.priority.value,
                "rationale": pi.rationale or "",
            }
            for pi in p.items
        ]
        return PlanComparisonSummary(
            version=p.version,
            task_count=len(p.items),
            total_duration_minutes=p.total_duration_minutes,
            scheduled_start=p.scheduled_start,
            scheduled_end=p.scheduled_end,
            risk_level=p.risk_level,
            is_feasible=p.is_feasible,
            status=p.status.value,
            items=items_payload,
        )

    # If only 1 plan exists and no explicit comparison requested
    if len(all_plans) == 1 and version_a is None and version_b is None:
        p1 = all_plans[0]
        meta = p1.metadata_ or {}
        stored_diff = meta.get("diff")
        if stored_diff:
            diff_obj = PlanDiff.model_validate(stored_diff)
            return ReplanningDiffResponse(
                plan_changed=True,
                status_label="PLAN CHANGED",
                reason=meta.get("replanning_reason", p1.reason or "PLAN_GENERATED"),
                why_explanation=diff_obj.why_changed,
                why_feasible=diff_obj.why_feasible,
                previous_plan=None,
                new_plan=summarize_plan(p1),
                changes=diff_obj,
                priority_changes=diff_obj.priority_changes,
                committed_at=p1.generated_at,
            )
        return ReplanningDiffResponse(
            plan_changed=False,
            status_label="INITIAL PLAN",
            reason="INITIAL_SCHEDULE_ACTIVE",
            why_explanation="Initial Plan v1 active. No replanning events have occurred yet.",
            why_feasible=p1.reason or "Initial schedule allocated based on available daily capacity.",
            new_plan=summarize_plan(p1),
            committed_at=p1.generated_at,
        )

    # Determine plan_b (newer plan)
    if version_b is not None:
        p_b = next((p for p in all_plans if p.version == version_b), None)
        if not p_b:
            p_b = all_plans[-1]
    else:
        p_b = all_plans[-1]

    # Determine plan_a (older plan)
    if version_a is not None:
        p_a = next((p for p in all_plans if p.version == version_a), None)
        if not p_a:
            p_a = next((p for p in all_plans if p.version < p_b.version), all_plans[0])
    else:
        p_a = next((p for p in reversed(all_plans) if p.version < p_b.version), None)

    if not p_a:
        # p_b is earliest plan
        return ReplanningDiffResponse(
            plan_changed=False,
            status_label="INITIAL PLAN",
            reason="INITIAL_SCHEDULE",
            why_explanation=f"Plan v{p_b.version} is the baseline version.",
            why_feasible=p_b.reason or "Scheduled within capacity.",
            new_plan=summarize_plan(p_b),
            committed_at=p_b.generated_at,
        )

    # 3. Check if stored diff exists on p_b matching p_a
    meta_b = p_b.metadata_ or {}
    stored_diff = meta_b.get("diff")
    diff_obj: PlanDiff | None = None
    if stored_diff and stored_diff.get("old_plan_version") == p_a.version:
        try:
            diff_obj = PlanDiff.model_validate(stored_diff)
        except Exception:
            diff_obj = None

    # 4. If no matching stored diff, dynamically construct the diff
    if not diff_obj:
        a_items_map = {pi.task_id: pi for pi in p_a.items}
        b_items_map = {pi.task_id: pi for pi in p_b.items}

        tasks_added: list[dict[str, Any]] = []
        tasks_removed: list[dict[str, Any]] = []
        tasks_rescheduled: list[TaskRescheduleItem] = []
        priority_changes: list[PriorityChangeItem] = []
        tasks_unaffected: list[dict[str, Any]] = []

        for tid, b_pi in b_items_map.items():
            t_title = b_pi.task.title if b_pi.task else "Task"
            if tid not in a_items_map:
                tasks_added.append(
                    {
                        "task_id": tid,
                        "title": t_title,
                        "priority": b_pi.priority,
                        "scheduled_start": b_pi.scheduled_start,
                        "scheduled_end": b_pi.scheduled_end,
                    }
                )
            else:
                a_pi = a_items_map[tid]
                diff_sec = (b_pi.scheduled_start - a_pi.scheduled_start).total_seconds()
                shift_hours = round(diff_sec / 3600.0, 2)

                if a_pi.priority != b_pi.priority:
                    priority_changes.append(
                        PriorityChangeItem(
                            task_id=tid,
                            title=t_title,
                            old_priority=a_pi.priority,
                            new_priority=b_pi.priority,
                            rationale=f"Priority shifted from {a_pi.priority.value} to {b_pi.priority.value}",
                        )
                    )

                if abs(shift_hours) >= 0.1:
                    tasks_rescheduled.append(
                        TaskRescheduleItem(
                            task_id=tid,
                            title=t_title,
                            priority=b_pi.priority,
                            old_start=a_pi.scheduled_start,
                            new_start=b_pi.scheduled_start,
                            old_end=a_pi.scheduled_end,
                            new_end=b_pi.scheduled_end,
                            shift_hours=shift_hours,
                            rationale=b_pi.rationale or f"Shifted by {shift_hours}h to adapt to schedule updates",
                        )
                    )
                else:
                    tasks_unaffected.append({"task_id": tid, "title": t_title})

        for tid, a_pi in a_items_map.items():
            if tid not in b_items_map:
                tasks_removed.append(
                    {
                        "task_id": tid,
                        "title": a_pi.task.title if a_pi.task else "Task",
                    }
                )

        why_changed = p_b.reason or meta_b.get("replanning_reason") or "Schedule modified to adapt to constraint changes."
        summary_parts = []
        if tasks_added:
            summary_parts.append(f"{len(tasks_added)} task(s) added")
        if tasks_removed:
            summary_parts.append(f"{len(tasks_removed)} task(s) removed")
        if tasks_rescheduled:
            summary_parts.append(f"{len(tasks_rescheduled)} task(s) rescheduled")
        if priority_changes:
            summary_parts.append(f"{len(priority_changes)} priority shift(s)")
        what_changed = ", ".join(summary_parts) if summary_parts else "Execution timeline shifted."

        why_feasible = (
            f"All {len(p_b.items)} tasks in Plan v{p_b.version} fit within available capacity with {p_b.risk_level} risk."
            if p_b.is_feasible
            else f"Plan requires attention: current risk rating is {p_b.risk_level}."
        )

        diff_obj = PlanDiff(
            old_plan_version=p_a.version,
            new_plan_version=p_b.version,
            why_changed=why_changed,
            what_changed=what_changed,
            tasks_added=tasks_added,
            tasks_removed=tasks_removed,
            tasks_rescheduled=tasks_rescheduled,
            priority_changes=priority_changes,
            tasks_unaffected=tasks_unaffected,
            critical_path_changed=False,
            old_risk_level=p_a.risk_level,
            new_risk_level=p_b.risk_level,
            old_completion_date=p_a.scheduled_end,
            new_completion_date=p_b.scheduled_end,
            why_feasible=why_feasible,
        )

    reason = (
        meta_b.get("replanning_reason")
        or (diff_obj.why_changed.split(":")[0].replace("Plan revised due to ", "") if ":" in diff_obj.why_changed else p_b.reason)
        or "CONSTRAINT_UPDATE"
    )

    return ReplanningDiffResponse(
        plan_changed=True,
        status_label="PLAN CHANGED",
        reason=reason,
        why_explanation=diff_obj.why_changed,
        why_feasible=diff_obj.why_feasible,
        previous_plan=summarize_plan(p_a),
        new_plan=summarize_plan(p_b),
        changes=diff_obj,
        priority_changes=diff_obj.priority_changes,
        committed_at=p_b.generated_at,
    )

