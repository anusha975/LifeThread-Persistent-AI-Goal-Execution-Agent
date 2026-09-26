import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.goal import Goal
from app.db.models.memory import Memory, MemoryStatus, MemoryType
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.schemas.memory import MemoryCreate, MemoryUpdate
from app.services.memory import MemoryService

logger = logging.getLogger("lifethread.api.memories")
audit_logger = logging.getLogger("lifethread.audit.memories")

router = APIRouter(prefix="/memories", tags=["Memory and Context"])


class MemoryCategory(StrEnum):
    """Categorical classification of user and agent memories."""

    GOAL_MEMORY = "Goal memory"
    PREFERENCE = "Preference"
    PAST_OUTCOME = "Past outcome"
    LEARNED_WEAKNESS = "Learned weakness"
    RELEVANT_KNOWLEDGE = "Relevant knowledge"


class RelatedGoalInfo(BaseModel):
    """Associated goal metadata."""

    id: str
    title: str


class MemorySourceDetail(BaseModel):
    """Detailed provenance metadata for inspecting memory source."""

    source_name: str
    provenance: str
    task_id: str | None = None
    task_title: str | None = None
    domain: str | None = None
    topic: str | None = None
    outcome_id: str | None = None
    epistemic_qualifier: str | None = None
    is_factual: bool | None = None
    is_hypothesis: bool | None = None
    user_corrected: bool = False
    corrected_at: str | None = None
    original_content: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class UserMemoryItem(BaseModel):
    """User-facing persistent memory entity with full transparent provenance."""

    id: str
    memory: str
    source: str
    source_details: MemorySourceDetail
    confidence: float
    importance_score: float
    category: MemoryCategory
    memory_type: str
    related_goal: RelatedGoalInfo | None = None
    status: str
    access_count: int
    created_at: str
    updated_at: str


class MemoryCorrectionRequest(BaseModel):
    """Payload for user correction of an existing memory."""

    content: str = Field(..., min_length=1, max_length=5000, description="Corrected memory statement")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Updated confidence level")
    category: MemoryCategory | None = Field(default=None, description="Updated memory category")


class MemoryCreateRequest(BaseModel):
    """Payload for creating a new memory record directly by user."""

    content: str = Field(..., min_length=1, max_length=5000, description="Memory statement")
    category: MemoryCategory = Field(default=MemoryCategory.PREFERENCE, description="Memory category")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score")
    goal_id: uuid.UUID | None = Field(default=None, description="Optional associated goal ID")


class MemoryListResponse(BaseModel):
    """Response containing memories and category distribution counts."""

    items: list[UserMemoryItem]
    total: int
    category_counts: dict[str, int]


def classify_memory_category(memory: Memory) -> MemoryCategory:
    """Classify a persistent memory into one of the 5 canonical user-facing categories."""
    meta = memory.metadata_json or {}
    learning_type = str(meta.get("learning_type", "")).upper()
    explicit_cat = str(meta.get("category", "")).strip().lower()

    # 1. Explicit category tag takes highest precedence
    if explicit_cat in ("learned weakness", "weakness"):
        return MemoryCategory.LEARNED_WEAKNESS
    if explicit_cat in ("preference",):
        return MemoryCategory.PREFERENCE
    if explicit_cat in ("goal memory", "goal"):
        return MemoryCategory.GOAL_MEMORY
    if explicit_cat in ("past outcome", "outcome"):
        return MemoryCategory.PAST_OUTCOME
    if explicit_cat in ("relevant knowledge", "knowledge"):
        return MemoryCategory.RELEVANT_KNOWLEDGE

    # 2. Learning type classification
    if learning_type == "WEAKNESS" or "weakness" in memory.content.lower():
        return MemoryCategory.LEARNED_WEAKNESS
    if learning_type == "PREFERENCE":
        return MemoryCategory.PREFERENCE
    if (
        learning_type in ("STRENGTH", "NEUTRAL_ROUTINE")
        or meta.get("outcome_id") is not None
        or meta.get("source_action") is not None
    ):
        return MemoryCategory.PAST_OUTCOME

    # 3. Model memory type classification
    if memory.memory_type == MemoryType.PREFERENCE:
        return MemoryCategory.PREFERENCE
    if memory.memory_type == MemoryType.GOAL:
        return MemoryCategory.GOAL_MEMORY
    if memory.memory_type == MemoryType.EPISODIC:
        return MemoryCategory.PAST_OUTCOME
    if memory.memory_type == MemoryType.SEMANTIC:
        return MemoryCategory.RELEVANT_KNOWLEDGE

    # 4. Fallback on goal association
    if meta.get("goal_id") is not None:
        return MemoryCategory.GOAL_MEMORY

    return MemoryCategory.GOAL_MEMORY


def build_source_details(memory: Memory) -> MemorySourceDetail:
    """Build inspectable source provenance structure from memory record and metadata."""
    meta = memory.metadata_json or {}
    return MemorySourceDetail(
        source_name=memory.source,
        provenance=str(meta.get("source_action") or meta.get("source_type") or memory.source),
        task_id=str(meta["task_id"]) if meta.get("task_id") else None,
        task_title=meta.get("task_title"),
        domain=meta.get("domain"),
        topic=meta.get("topic"),
        outcome_id=meta.get("outcome_id"),
        epistemic_qualifier=meta.get("epistemic_qualifier"),
        is_factual=meta.get("is_factual"),
        is_hypothesis=meta.get("is_hypothesis"),
        user_corrected=bool(meta.get("user_corrected", False)),
        corrected_at=meta.get("corrected_at"),
        original_content=meta.get("original_content"),
        raw_metadata=meta,
    )


@router.get(
    "",
    response_model=MemoryListResponse,
    summary="List Persisted User Memories",
    description="Retrieve all memories remembered by LifeThread with category filters, source inspection, and goal linkage.",
)
async def list_memories(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Annotated[
        MemoryCategory | None, Query(description="Filter by one of the 5 canonical memory categories")
    ] = None,
    goal_id: Annotated[uuid.UUID | None, Query(description="Filter memories linked to a specific goal")] = None,
    query: Annotated[str | None, Query(description="Search memory text content")] = None,
    status_filter: Annotated[
        MemoryStatus | None, Query(alias="status", description="Filter by lifecycle status")
    ] = MemoryStatus.ACTIVE,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemoryListResponse:
    """Retrieve all real persisted memories for the authenticated user."""
    # Query base memories
    stmt = select(Memory).where(Memory.user_id == current_user.id)
    if status_filter is not None:
        stmt = stmt.where(Memory.status == status_filter)

    if query and query.strip():
        stmt = stmt.where(Memory.content.ilike(f"%{query.strip()}%"))

    # Order newest first
    stmt = stmt.order_by(Memory.created_at.desc())
    res = await db.execute(stmt)
    all_user_memories = res.scalars().all()

    # Collect goal IDs for bulk title resolution
    goal_id_set = set()
    for mem in all_user_memories:
        meta = mem.metadata_json or {}
        gid = meta.get("goal_id")
        if gid:
            try:
                goal_id_set.add(uuid.UUID(str(gid)))
            except (ValueError, TypeError):
                pass

    goals_map: dict[str, str] = {}
    if goal_id_set:
        g_stmt = select(Goal.id, Goal.title).where(Goal.id.in_(goal_id_set), Goal.user_id == current_user.id)
        g_res = await db.execute(g_stmt)
        goals_map = {str(gid): gtitle for gid, gtitle in g_res.all()}

    # Compute category counts across all user memories
    category_counts: dict[str, int] = {
        MemoryCategory.GOAL_MEMORY.value: 0,
        MemoryCategory.PREFERENCE.value: 0,
        MemoryCategory.PAST_OUTCOME.value: 0,
        MemoryCategory.LEARNED_WEAKNESS.value: 0,
        MemoryCategory.RELEVANT_KNOWLEDGE.value: 0,
    }

    filtered_items: list[UserMemoryItem] = []

    for mem in all_user_memories:
        mem_cat = classify_memory_category(mem)
        category_counts[mem_cat.value] = category_counts.get(mem_cat.value, 0) + 1

        # Apply category filter
        if category is not None and mem_cat != category:
            continue

        # Apply goal filter
        meta = mem.metadata_json or {}
        mem_goal_id = meta.get("goal_id")
        if goal_id is not None:
            if not mem_goal_id or str(mem_goal_id) != str(goal_id):
                continue

        # Resolve related goal
        related_goal: RelatedGoalInfo | None = None
        if mem_goal_id:
            gid_str = str(mem_goal_id)
            title = goals_map.get(gid_str) or meta.get("goal_title") or "Associated Goal"
            related_goal = RelatedGoalInfo(id=gid_str, title=title)

        source_details = build_source_details(mem)

        filtered_items.append(
            UserMemoryItem(
                id=str(mem.id),
                memory=mem.content,
                source=mem.source,
                source_details=source_details,
                confidence=mem.confidence,
                importance_score=mem.importance_score,
                category=mem_cat,
                memory_type=mem.memory_type.value,
                related_goal=related_goal,
                status=mem.status.value,
                access_count=mem.access_count,
                created_at=mem.created_at.isoformat(),
                updated_at=mem.updated_at.isoformat(),
            )
        )

    total = len(filtered_items)
    paginated_items = filtered_items[offset : offset + limit]

    return MemoryListResponse(
        items=paginated_items,
        total=total,
        category_counts=category_counts,
    )


@router.get(
    "/{memory_id}",
    response_model=UserMemoryItem,
    summary="Get Specific Memory Detail",
    description="Retrieve full details for a memory, including inspectable source metadata.",
)
async def get_memory(
    memory_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserMemoryItem:
    """Retrieve a single memory ensuring tenant isolation."""
    mem = await MemoryService.get_memory_by_id(
        db=db, memory_id=memory_id, user_id=current_user.id, record_access=True
    )

    mem_cat = classify_memory_category(mem)
    meta = mem.metadata_json or {}

    related_goal: RelatedGoalInfo | None = None
    mem_goal_id = meta.get("goal_id")
    if mem_goal_id:
        gid_str = str(mem_goal_id)
        g_stmt = select(Goal.title).where(Goal.id == uuid.UUID(gid_str), Goal.user_id == current_user.id)
        g_res = await db.execute(g_stmt)
        g_title = g_res.scalar() or meta.get("goal_title") or "Associated Goal"
        related_goal = RelatedGoalInfo(id=gid_str, title=g_title)

    return UserMemoryItem(
        id=str(mem.id),
        memory=mem.content,
        source=mem.source,
        source_details=build_source_details(mem),
        confidence=mem.confidence,
        importance_score=mem.importance_score,
        category=mem_cat,
        memory_type=mem.memory_type.value,
        related_goal=related_goal,
        status=mem.status.value,
        access_count=mem.access_count,
        created_at=mem.created_at.isoformat(),
        updated_at=mem.updated_at.isoformat(),
    )


@router.post(
    "",
    response_model=UserMemoryItem,
    status_code=status.HTTP_201_CREATED,
    summary="Create User Memory",
    description="Manually record a preference or goal memory.",
)
async def create_memory(
    request: MemoryCreateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserMemoryItem:
    """Store a user-provided memory."""
    # Map category to DB memory type
    type_map = {
        MemoryCategory.GOAL_MEMORY: MemoryType.GOAL,
        MemoryCategory.PREFERENCE: MemoryType.PREFERENCE,
        MemoryCategory.PAST_OUTCOME: MemoryType.EPISODIC,
        MemoryCategory.LEARNED_WEAKNESS: MemoryType.SEMANTIC,
        MemoryCategory.RELEVANT_KNOWLEDGE: MemoryType.SEMANTIC,
    }
    db_type = type_map.get(request.category, MemoryType.PREFERENCE)

    meta: dict[str, Any] = {
        "category": request.category.value,
        "created_by": "user",
    }

    related_goal: RelatedGoalInfo | None = None
    if request.goal_id:
        g_stmt = select(Goal.title).where(Goal.id == request.goal_id, Goal.user_id == current_user.id)
        g_res = await db.execute(g_stmt)
        title = g_res.scalar()
        if not title:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated goal not found")
        meta["goal_id"] = str(request.goal_id)
        meta["goal_title"] = title
        related_goal = RelatedGoalInfo(id=str(request.goal_id), title=title)

    mem_create = MemoryCreate(
        content=request.content,
        memory_type=db_type,
        confidence=request.confidence,
        importance_score=0.7,
        source="user",
        metadata=meta,
        deduplicate=True,
    )

    mem = await MemoryService.store_memory(
        db=db,
        user_id=current_user.id,
        create_data=mem_create,
    )

    return UserMemoryItem(
        id=str(mem.id),
        memory=mem.content,
        source=mem.source,
        source_details=build_source_details(mem),
        confidence=mem.confidence,
        importance_score=mem.importance_score,
        category=request.category,
        memory_type=mem.memory_type.value,
        related_goal=related_goal,
        status=mem.status.value,
        access_count=mem.access_count,
        created_at=mem.created_at.isoformat(),
        updated_at=mem.updated_at.isoformat(),
    )


@router.patch(
    "/{memory_id}",
    response_model=UserMemoryItem,
    summary="Correct a Persisted Memory",
    description="Allows users to transparently edit or correct the content, category, or confidence of a memory.",
)
async def correct_memory(
    memory_id: uuid.UUID,
    request: MemoryCorrectionRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserMemoryItem:
    """Correct a memory statement, recording transparent audit provenance."""
    mem = await MemoryService.get_memory_by_id(
        db=db, memory_id=memory_id, user_id=current_user.id, record_access=False
    )

    now = datetime.now(UTC)
    meta = dict(mem.metadata_json or {})

    # Preserve audit history
    if not meta.get("user_corrected"):
        meta["original_content"] = mem.content
    meta["user_corrected"] = True
    meta["corrected_at"] = now.isoformat()

    if request.category:
        meta["category"] = request.category.value
        # Re-assign memory_type if appropriate
        if request.category == MemoryCategory.PREFERENCE:
            mem.memory_type = MemoryType.PREFERENCE
        elif request.category == MemoryCategory.GOAL_MEMORY:
            mem.memory_type = MemoryType.GOAL
        elif request.category == MemoryCategory.PAST_OUTCOME:
            mem.memory_type = MemoryType.EPISODIC
        elif request.category == MemoryCategory.LEARNED_WEAKNESS:
            meta["learning_type"] = "WEAKNESS"

    update_payload = MemoryUpdate(
        content=request.content,
        confidence=request.confidence if request.confidence is not None else mem.confidence,
        metadata=meta,
    )

    updated_mem = await MemoryService.update_memory(
        db=db,
        memory_id=memory_id,
        user_id=current_user.id,
        update_data=update_payload,
    )

    audit_logger.info(
        "AUDIT [USER_CORRECTED_MEMORY] user_id=%s memory_id=%s original='%s' corrected='%s'",
        current_user.id,
        memory_id,
        meta.get("original_content", mem.content),
        request.content,
    )

    mem_cat = classify_memory_category(updated_mem)

    related_goal: RelatedGoalInfo | None = None
    mem_goal_id = meta.get("goal_id")
    if mem_goal_id:
        gid_str = str(mem_goal_id)
        g_stmt = select(Goal.title).where(Goal.id == uuid.UUID(gid_str), Goal.user_id == current_user.id)
        g_res = await db.execute(g_stmt)
        g_title = g_res.scalar() or meta.get("goal_title") or "Associated Goal"
        related_goal = RelatedGoalInfo(id=gid_str, title=g_title)

    return UserMemoryItem(
        id=str(updated_mem.id),
        memory=updated_mem.content,
        source=updated_mem.source,
        source_details=build_source_details(updated_mem),
        confidence=updated_mem.confidence,
        importance_score=updated_mem.importance_score,
        category=mem_cat,
        memory_type=updated_mem.memory_type.value,
        related_goal=related_goal,
        status=updated_mem.status.value,
        access_count=updated_mem.access_count,
        created_at=updated_mem.created_at.isoformat(),
        updated_at=updated_mem.updated_at.isoformat(),
    )


@router.delete(
    "/{memory_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a Persisted Memory",
    description="Permits users to completely delete or purge a memory from LifeThread's persistence.",
)
async def delete_memory(
    memory_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    hard_delete: Annotated[bool, Query(description="Whether to purge permanently from storage")] = True,
) -> dict[str, Any]:
    """Delete a memory entry with tenant ownership enforcement."""
    success = await MemoryService.delete_memory(
        db=db,
        memory_id=memory_id,
        user_id=current_user.id,
        hard_delete=hard_delete,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' not found",
        )

    return {
        "success": True,
        "message": "Memory deleted successfully",
        "memory_id": str(memory_id),
    }


@router.get(
    "/{memory_id}/source",
    response_model=MemorySourceDetail,
    summary="Inspect Memory Source Provenance",
    description="Retrieve deep source inspection data for a memory: originating action, task, outcome, benchmarks, and qualifiers.",
)
async def inspect_memory_source(
    memory_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MemorySourceDetail:
    """Inspect detailed source provenance for a specific memory."""
    mem = await MemoryService.get_memory_by_id(
        db=db, memory_id=memory_id, user_id=current_user.id, record_access=False
    )
    return build_source_details(mem)
