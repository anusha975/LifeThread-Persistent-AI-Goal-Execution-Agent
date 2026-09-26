import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LifeThreadException
from app.db.models.goal import GoalMilestone, GoalPriority, MilestoneStatus
from app.db.models.task import GoalDecomposition, Task, TaskDependency, TaskStatus
from app.schemas.decomposition import (
    DecompositionRequest,
    GoalDecompositionResponse,
    TaskDependencyGraphResponse,
    TaskDependencyResponse,
    TaskListResponse,
    TaskResponse,
    TaskUpdate,
)
from app.schemas.goal import GoalMilestoneResponse
from app.services.critical_path import CriticalPathService
from app.services.dependency_graph import DependencyGraphService
from app.services.goal import GoalService
from app.services.llm import BaseLLMProvider, LLMMessage, get_llm_provider

logger = logging.getLogger("lifethread.services.decomposition")


class _LLMTaskItem(BaseModel):
    temp_id: str
    milestone_index: int = 0
    title: str = Field(..., min_length=1)
    description: str | None = None
    priority: str = "MEDIUM"
    estimated_minutes: int = Field(default=60, ge=1)


class _LLMDependencyItem(BaseModel):
    task_temp_id: str
    depends_on_temp_id: str
    dependency_type: str = "BLOCKS"


class _LLMDecompositionPayload(BaseModel):
    milestones: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[_LLMTaskItem] = Field(default_factory=list)
    dependencies: list[_LLMDependencyItem] = Field(default_factory=list)


class DecompositionService:
    """Service to orchestrate goal decomposition into milestones, tasks, and dependency DAGs."""

    DECOMPOSITION_PROMPT = """You are the LifeThread Goal Decomposition Engine.
Decompose the following validated Goal into progressive milestones, actionable tasks, and a verified dependency graph.

STRICT RULES:
1. Output MUST be a single, valid JSON object with NO markdown wrapping or surrounding conversational text.
2. Generate 2 to 5 progressive milestones that guide the goal to completion.
3. Generate 3 to 15 actionable, concrete tasks. Each task must have a unique `temp_id` (e.g. "T1", "T2", ...).
4. Specify prerequisites in `dependencies`. If task T2 cannot begin until T1 is completed, record {"task_temp_id": "T2", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"}.
5. CRITICAL: The dependency graph MUST BE A DIRECTED ACYCLIC GRAPH (DAG). NEVER create cyclical dependencies (e.g. T1 depends on T2 and T2 depends on T1).
6. Estimate realistic effort in `estimated_minutes` (e.g. 30, 60, 120, 240).

Expected JSON Structure:
{
  "milestones": [
    {"title": "Phase 1: Setup", "description": "Environment and setup", "order_index": 0}
  ],
  "tasks": [
    {
      "temp_id": "T1",
      "milestone_index": 0,
      "title": "Set up codebase and tooling",
      "description": "Configure dependencies and linting",
      "priority": "HIGH",
      "estimated_minutes": 60
    },
    {
      "temp_id": "T2",
      "milestone_index": 0,
      "title": "Implement core service",
      "description": "Write initial implementation",
      "priority": "MEDIUM",
      "estimated_minutes": 120
    }
  ],
  "dependencies": [
    {"task_temp_id": "T2", "depends_on_temp_id": "T1", "dependency_type": "BLOCKS"}
  ]
}
"""

    @classmethod
    async def decompose_goal(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        request: DecompositionRequest,
        llm_provider: BaseLLMProvider | None = None,
    ) -> GoalDecompositionResponse:
        """Decompose a goal into milestones, tasks, and dependencies, preserving revision history."""
        # 1. Ensure goal exists and belongs to the authenticated user
        goal = await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)

        # 2. Check existing decompositions and enforce version preservation
        existing_decomp_query = (
            select(GoalDecomposition)
            .where(GoalDecomposition.goal_id == goal_id)
            .order_by(GoalDecomposition.version.desc())
        )
        decomp_result = await db.execute(existing_decomp_query)
        existing_decomps = decomp_result.scalars().all()

        if existing_decomps:
            latest_version = existing_decomps[0].version
            if not request.confirm_new_version:
                logger.warning(
                    f"Refusing to overwrite existing decomposition for goal {goal_id} (current v{latest_version})"
                )
                raise LifeThreadException(
                    message=(
                        f"Goal already has an existing decomposition (version {latest_version}). "
                        "To generate a new decomposition revision, set confirm_new_version=true."
                    ),
                    code="DECOMPOSITION_ALREADY_EXISTS",
                    status_code=status.HTTP_409_CONFLICT,
                    details={"latest_version": latest_version},
                )
            new_version = latest_version + 1
            # Mark previous active versions as inactive
            for ed in existing_decomps:
                if ed.is_active:
                    ed.is_active = False
        else:
            new_version = 1

        # 3. Call LLM for decomposition structure
        provider = llm_provider or get_llm_provider()
        goal_context = f"""Goal Title: {goal.title}
Objective: {goal.objective}
Description: {goal.description or "None"}
Deadline: {goal.deadline.isoformat() if goal.deadline else "None"}
Priority: {goal.priority.value}
Success Criteria: {json.dumps(goal.success_criteria)}
Existing Milestones: {[m.title for m in goal.milestones]}
Max Tasks: {request.max_tasks}
"""
        messages = [
            LLMMessage(role="system", content=cls.DECOMPOSITION_PROMPT),
            LLMMessage(role="user", content=goal_context),
        ]

        logger.info(f"Generating decomposition for goal {goal_id} (version {new_version})")
        response = await provider.chat(messages=messages, temperature=0.3)

        # 4. Parse LLM response safely
        decomp_data = cls._parse_decomposition_json(response.content)

        # 5. Resolve Milestones
        milestone_models: list[GoalMilestone] = list(goal.milestones)
        if not milestone_models and decomp_data.milestones:
            for idx, m_dict in enumerate(decomp_data.milestones):
                m_model = GoalMilestone(
                    goal_id=goal_id,
                    title=str(m_dict.get("title", f"Phase {idx + 1}")).strip(),
                    description=m_dict.get("description"),
                    order_index=int(m_dict.get("order_index", idx)),
                    status=MilestoneStatus.PENDING,
                )
                db.add(m_model)
                milestone_models.append(m_model)
            await db.flush()

        # 6. Map temporary task IDs to temporary index and validate DAG
        temp_id_list = [t.temp_id for t in decomp_data.tasks]
        if not temp_id_list:
            raise LifeThreadException(
                message="Decomposition engine produced 0 actionable tasks",
                code="EMPTY_DECOMPOSITION",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Temporary UUID mapping for graph analysis
        temp_to_uuid: dict[str, uuid.UUID] = {tid: uuid.uuid4() for tid in temp_id_list}
        temp_edges: list[tuple[uuid.UUID, uuid.UUID]] = []

        for dep in decomp_data.dependencies:
            if dep.task_temp_id in temp_to_uuid and dep.depends_on_temp_id in temp_to_uuid:
                prereq_uuid = temp_to_uuid[dep.depends_on_temp_id]
                task_uuid = temp_to_uuid[dep.task_temp_id]
                temp_edges.append((prereq_uuid, task_uuid))

        # Check for cycles using DependencyGraphService
        cycle = DependencyGraphService.detect_cycles(
            task_ids=list(temp_to_uuid.values()),
            dependencies=temp_edges,
        )
        if cycle:
            # Map back to readable temp IDs
            uuid_to_temp = {v: k for k, v in temp_to_uuid.items()}
            cycle_temps = [uuid_to_temp.get(cid, str(cid)) for cid in cycle]
            cycle_desc = " -> ".join(cycle_temps)
            logger.warning(f"Rejecting cyclical decomposition: {cycle_desc}")
            raise LifeThreadException(
                message=f"Circular dependency detected in tasks: {cycle_desc}",
                code="CIRCULAR_DEPENDENCY_DETECTED",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"cycle": cycle_temps},
            )

        # 7. Create real Task entities in database
        uuid_to_task_model: dict[uuid.UUID, Task] = {}
        for t_item in decomp_data.tasks:
            assigned_milestone_id = None
            if milestone_models:
                m_idx = min(max(0, t_item.milestone_index), len(milestone_models) - 1)
                assigned_milestone_id = milestone_models[m_idx].id

            priority_enum = GoalPriority.MEDIUM
            if t_item.priority.upper() in GoalPriority.__members__:
                priority_enum = GoalPriority(t_item.priority.upper())

            task_model = Task(
                goal_id=goal_id,
                milestone_id=assigned_milestone_id,
                version=new_version,
                title=t_item.title.strip(),
                description=t_item.description,
                status=TaskStatus.PENDING,
                priority=priority_enum,
                estimated_minutes=max(1, t_item.estimated_minutes),
            )
            db.add(task_model)
            uuid_to_task_model[temp_to_uuid[t_item.temp_id]] = task_model

        await db.flush()

        # 8. Create real TaskDependency entities
        real_dependencies: list[TaskDependency] = []
        real_edges: list[tuple[uuid.UUID, uuid.UUID]] = []

        for dep in decomp_data.dependencies:
            if dep.task_temp_id in temp_to_uuid and dep.depends_on_temp_id in temp_to_uuid:
                t_model = uuid_to_task_model[temp_to_uuid[dep.task_temp_id]]
                prereq_model = uuid_to_task_model[temp_to_uuid[dep.depends_on_temp_id]]
                if t_model.id != prereq_model.id:
                    dep_model = TaskDependency(
                        task_id=t_model.id,
                        depends_on_task_id=prereq_model.id,
                        dependency_type=dep.dependency_type or "BLOCKS",
                    )
                    db.add(dep_model)
                    real_dependencies.append(dep_model)
                    real_edges.append((prereq_model.id, t_model.id))

        await db.flush()

        # 9. Calculate Critical Path using real Task models
        created_task_list = list(uuid_to_task_model.values())
        critical_path_ids, total_duration, _ = CriticalPathService.calculate_critical_path(
            tasks=created_task_list,
            dependencies=real_edges,
        )

        # 10. Record GoalDecomposition version snapshot
        decomp_record = GoalDecomposition(
            goal_id=goal_id,
            version=new_version,
            task_count=len(created_task_list),
            critical_path_duration_minutes=total_duration,
            is_active=True,
            metadata_={"critical_path_task_ids": [str(cid) for cid in critical_path_ids]},
        )
        db.add(decomp_record)
        await db.flush()

        # Build responses
        task_responses = [TaskResponse.model_validate(t) for t in created_task_list]
        dep_responses = [TaskDependencyResponse.model_validate(d) for d in real_dependencies]
        milestone_responses = [GoalMilestoneResponse.model_validate(m) for m in milestone_models]

        return GoalDecompositionResponse(
            goal_id=goal_id,
            version=new_version,
            is_active=True,
            milestones=milestone_responses,
            tasks=task_responses,
            dependencies=dep_responses,
            critical_path_task_ids=critical_path_ids,
            critical_path_duration_minutes=total_duration,
            has_cycles=False,
            created_at=decomp_record.created_at,
            metadata=decomp_record.metadata_,
        )

    @classmethod
    async def list_goal_tasks(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        version: int | None = None,
        status_filter: TaskStatus | None = None,
    ) -> TaskListResponse:
        """Retrieve tasks belonging to a specific goal decomposition version."""
        await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)

        target_version = version
        if target_version is None:
            active_q = select(GoalDecomposition.version).where(
                GoalDecomposition.goal_id == goal_id,
                GoalDecomposition.is_active.is_(True),
            )
            v_res = await db.execute(active_q)
            target_version = v_res.scalar_one_or_none()

            if target_version is None:
                max_v_q = select(func.max(Task.version)).where(Task.goal_id == goal_id)
                max_res = await db.execute(max_v_q)
                target_version = max_res.scalar() or 1

        query = select(Task).where(Task.goal_id == goal_id, Task.version == target_version)
        if status_filter is not None:
            query = query.where(Task.status == status_filter)

        query = query.order_by(Task.created_at.asc())
        result = await db.execute(query)
        tasks = result.scalars().all()

        task_responses = [TaskResponse.model_validate(t) for t in tasks]
        return TaskListResponse(
            goal_id=goal_id,
            version=target_version,
            items=task_responses,
            total=len(task_responses),
        )

    @classmethod
    async def update_task(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        task_in: TaskUpdate,
    ) -> Task:
        """Update mutable fields on a goal task."""
        await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)
        stmt = select(Task).where(Task.id == task_id, Task.goal_id == goal_id)
        res = await db.execute(stmt)
        task = res.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

        update_data = task_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(task, field, value)

        if task.status == TaskStatus.COMPLETED and not task.completed_at:
            task.completed_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(task)
        return task

    @classmethod
    async def complete_task(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Task:
        """Mark a goal task as completed."""
        await GoalService.get_goal_by_id(db=db, goal_id=goal_id, user_id=user_id)
        stmt = select(Task).where(Task.id == task_id, Task.goal_id == goal_id)
        res = await db.execute(stmt)
        task = res.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(task)
        return task

    @classmethod
    async def get_goal_dependencies(
        cls,
        db: AsyncSession,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        version: int | None = None,
    ) -> TaskDependencyGraphResponse:
        """Retrieve the task dependency DAG, critical path, and topological order for a goal."""
        task_list_resp = await cls.list_goal_tasks(
            db=db,
            goal_id=goal_id,
            user_id=user_id,
            version=version,
        )

        target_version = task_list_resp.version
        tasks = task_list_resp.items
        task_ids = [t.id for t in tasks]

        if not task_ids:
            return TaskDependencyGraphResponse(
                goal_id=goal_id,
                version=target_version,
                nodes=[],
                edges=[],
                critical_path=[],
                topological_order=[],
                critical_path_duration_minutes=0,
            )

        # Retrieve dependencies where task_id belongs to this version's tasks
        dep_query = select(TaskDependency).where(TaskDependency.task_id.in_(task_ids))
        dep_result = await db.execute(dep_query)
        dependencies = dep_result.scalars().all()

        edges = [(d.depends_on_task_id, d.task_id) for d in dependencies]
        topological_order = DependencyGraphService.topological_sort(task_ids, edges)
        critical_path_ids, total_duration, _ = CriticalPathService.calculate_critical_path(
            tasks=tasks,
            dependencies=edges,
            topological_order=topological_order,
        )

        dep_responses = [TaskDependencyResponse.model_validate(d) for d in dependencies]

        return TaskDependencyGraphResponse(
            goal_id=goal_id,
            version=target_version,
            nodes=tasks,
            edges=dep_responses,
            critical_path=critical_path_ids,
            topological_order=topological_order,
            critical_path_duration_minutes=total_duration,
        )

    @classmethod
    def _parse_decomposition_json(cls, raw_content: str) -> _LLMDecompositionPayload:
        """Extract and validate decomposition payload from LLM output."""
        if not raw_content or not raw_content.strip():
            raise LifeThreadException(
                message="Malformed LLM response: Empty decomposition received",
                code="MALFORMED_LLM_OUTPUT",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        cleaned = raw_content.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            cleaned = cleaned[start_idx : end_idx + 1]

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LifeThreadException(
                message="Malformed LLM response: Invalid JSON in decomposition output",
                code="MALFORMED_LLM_OUTPUT",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"error": str(exc), "raw": raw_content[:200]},
            ) from exc

        try:
            return _LLMDecompositionPayload.model_validate(parsed)
        except Exception as exc:
            raise LifeThreadException(
                message="Malformed LLM response: Decomposition schema validation failed",
                code="MALFORMED_LLM_OUTPUT",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"validation_error": str(exc)},
            ) from exc
