import logging
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory import Memory, MemoryStatus, MemoryType
from app.schemas.memory import LifecycleRuleResult, MemoryCreate, MemoryUpdate
from app.services.embeddings.base import BaseEmbeddingProvider

logger = logging.getLogger("lifethread.services.memory")
audit_logger = logging.getLogger("lifethread.audit.memory")


class MemoryService:
    """Core domain Memory Engine for persistent relational memory lifecycle, storage, and retrieval."""

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text for consistent duplicate detection and matching."""
        # Convert to lowercase, strip leading/trailing whitespace, and collapse spaces
        clean = text.lower().strip()
        clean = re.sub(r"\s+", " ", clean)
        return clean

    @classmethod
    async def detect_duplicate(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        content: str,
        memory_type: MemoryType | None = None,
    ) -> Memory | None:
        """Detect if an active memory with identical normalized content already exists for this user."""
        norm_input = cls.normalize_text(content)

        stmt = select(Memory).where(
            Memory.user_id == user_id,
            Memory.status == MemoryStatus.ACTIVE,
        )
        if memory_type is not None:
            stmt = stmt.where(Memory.memory_type == memory_type)

        res = await db.execute(stmt)
        candidates = res.scalars().all()

        for cand in candidates:
            if cls.normalize_text(cand.content) == norm_input:
                return cand
        return None

    @classmethod
    async def store_memory(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        create_data: MemoryCreate,
        embedding: list[float] | None = None,
        embedding_provider: BaseEmbeddingProvider | None = None,
    ) -> Memory:
        """Store a new memory record relationally with duplicate detection, importance scoring, and audit logging."""
        now = datetime.now(UTC)

        # 1. Duplicate detection and reinforcement
        if create_data.deduplicate:
            duplicate = await cls.detect_duplicate(
                db=db,
                user_id=user_id,
                content=create_data.content,
                memory_type=create_data.memory_type,
            )
            if duplicate is not None:
                # Reinforce existing memory instead of creating redundant duplicate
                duplicate.access_count += 1
                duplicate.last_accessed_at = now
                duplicate.importance_score = min(
                    1.0, max(duplicate.importance_score, create_data.importance_score)
                )
                duplicate.confidence = min(
                    1.0, round(max(duplicate.confidence, create_data.confidence) + 0.05, 3)
                )

                # Merge metadata
                merged_meta = dict(duplicate.metadata_json or {})
                if create_data.metadata:
                    merged_meta.update(create_data.metadata)
                merged_meta["last_reinforced_at"] = now.isoformat()
                duplicate.metadata_json = merged_meta

                await db.flush()
                await db.refresh(duplicate)

                audit_logger.info(
                    "AUDIT [MEMORY_REINFORCED_DUPLICATE] user_id=%s memory_id=%s type=%s importance=%s confidence=%s",
                    user_id,
                    duplicate.id,
                    duplicate.memory_type.value,
                    duplicate.importance_score,
                    duplicate.confidence,
                )
                return duplicate

        # 2. Embedding generation with graceful failure handling (Requirement 9 & 10)
        computed_embedding: list[float] | None = embedding
        if computed_embedding is None and embedding_provider is not None:
            try:
                computed_embedding = await embedding_provider.generate_embedding(
                    create_data.content
                )
            except Exception as e:
                logger.warning(
                    "Embedding generation failed for memory: %s. Preserving original memory text.",
                    e,
                )
                audit_logger.warning(
                    "AUDIT [MEMORY_EMBEDDING_FAILED] user_id=%s error=%s",
                    user_id,
                    str(e),
                )
                computed_embedding = None

        # 3. Persist new memory
        memory = Memory(
            user_id=user_id,
            memory_type=create_data.memory_type,
            content=create_data.content,
            importance_score=create_data.importance_score,
            confidence=create_data.confidence,
            source=create_data.source,
            status=MemoryStatus.ACTIVE,
            access_count=0,
            last_accessed_at=now,
            metadata_json=create_data.metadata,
            embedding=computed_embedding,
        )
        db.add(memory)
        await db.flush()
        await db.refresh(memory)

        audit_logger.info(
            "AUDIT [MEMORY_STORED] user_id=%s memory_id=%s type=%s importance=%s confidence=%s source=%s",
            user_id,
            memory.id,
            memory.memory_type.value,
            memory.importance_score,
            memory.confidence,
            memory.source,
        )
        return memory

    @classmethod
    async def get_memory_by_id(
        cls,
        db: AsyncSession,
        memory_id: uuid.UUID,
        user_id: uuid.UUID,
        record_access: bool = True,
    ) -> Memory:
        """Retrieve a specific memory enforcing strict user ownership and updating access tracking.

        Detects and logs IDOR attempts if the memory belongs to another user.

        Raises:
            HTTPException: 404 if memory does not exist or belongs to another user.
        """
        from app.db.access_control import DatabaseAccessControl

        memory = await DatabaseAccessControl.get_user_resource_or_404(
            db=db,
            model=Memory,
            resource_id=memory_id,
            user_id=user_id,
            resource_name="memory",
        )

        if record_access:
            memory.access_count += 1
            memory.last_accessed_at = datetime.now(UTC)
            await db.flush()
            await db.refresh(memory)

        audit_logger.info(
            "AUDIT [MEMORY_RETRIEVED] user_id=%s memory_id=%s type=%s accesses=%s",
            user_id,
            memory.id,
            memory.memory_type.value,
            memory.access_count,
        )
        return memory

    @classmethod
    async def search_memories(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        query: str | None = None,
        memory_type: MemoryType | None = None,
        min_importance: float | None = None,
        min_confidence: float | None = None,
        source: str | None = None,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Memory], int]:
        """Search memories using relational matching with strict user isolation and access updating."""
        stmt = select(Memory).where(Memory.user_id == user_id)
        count_stmt = select(func.count()).select_from(Memory).where(Memory.user_id == user_id)

        if status is not None:
            stmt = stmt.where(Memory.status == status)
            count_stmt = count_stmt.where(Memory.status == status)

        if query:
            clean_q = f"%{query.strip()}%"
            stmt = stmt.where(Memory.content.ilike(clean_q))
            count_stmt = count_stmt.where(Memory.content.ilike(clean_q))

        if memory_type is not None:
            stmt = stmt.where(Memory.memory_type == memory_type)
            count_stmt = count_stmt.where(Memory.memory_type == memory_type)

        if min_importance is not None:
            stmt = stmt.where(Memory.importance_score >= min_importance)
            count_stmt = count_stmt.where(Memory.importance_score >= min_importance)

        if min_confidence is not None:
            stmt = stmt.where(Memory.confidence >= min_confidence)
            count_stmt = count_stmt.where(Memory.confidence >= min_confidence)

        if source is not None:
            stmt = stmt.where(Memory.source == source)
            count_stmt = count_stmt.where(Memory.source == source)

        if created_after is not None:
            stmt = stmt.where(Memory.created_at >= created_after)
            count_stmt = count_stmt.where(Memory.created_at >= created_after)

        if created_before is not None:
            stmt = stmt.where(Memory.created_at <= created_before)
            count_stmt = count_stmt.where(Memory.created_at <= created_before)

        # Count total
        count_res = await db.execute(count_stmt)
        total = count_res.scalar() or 0

        # Order by highest importance first, then newest
        stmt = (
            stmt.order_by(Memory.importance_score.desc(), Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await db.execute(stmt)
        memories = res.scalars().all()

        audit_logger.info(
            "AUDIT [MEMORY_SEARCH] user_id=%s query=%s type=%s min_importance=%s count=%s total=%s",
            user_id,
            query,
            memory_type.value if memory_type else None,
            min_importance,
            len(memories),
            total,
        )
        return memories, total

    @classmethod
    async def update_memory(
        cls,
        db: AsyncSession,
        memory_id: uuid.UUID,
        user_id: uuid.UUID,
        update_data: MemoryUpdate,
        embedding_provider: BaseEmbeddingProvider | None = None,
    ) -> Memory:
        """Update an existing memory with validation, user isolation, and audit logging."""
        memory = await cls.get_memory_by_id(
            db=db, memory_id=memory_id, user_id=user_id, record_access=False
        )

        if update_data.content is not None and update_data.content != memory.content:
            memory.content = update_data.content
            if embedding_provider is not None:
                try:
                    memory.embedding = await embedding_provider.generate_embedding(
                        update_data.content
                    )
                except Exception as e:
                    logger.warning(
                        "Embedding regeneration failed on update: %s. Preserving original memory text.",
                        e,
                    )
                    audit_logger.warning(
                        "AUDIT [MEMORY_EMBEDDING_UPDATE_FAILED] user_id=%s memory_id=%s error=%s",
                        user_id,
                        memory_id,
                        str(e),
                    )
        if update_data.memory_type is not None:
            memory.memory_type = update_data.memory_type
        if update_data.importance_score is not None:
            memory.importance_score = update_data.importance_score
        if update_data.confidence is not None:
            memory.confidence = update_data.confidence
        if update_data.source is not None:
            memory.source = update_data.source
        if update_data.status is not None:
            memory.status = update_data.status
        if update_data.metadata is not None:
            memory.metadata_json = update_data.metadata

        await db.flush()
        await db.refresh(memory)

        audit_logger.info(
            "AUDIT [MEMORY_UPDATED] user_id=%s memory_id=%s type=%s importance=%s confidence=%s",
            user_id,
            memory.id,
            memory.memory_type.value,
            memory.importance_score,
            memory.confidence,
        )
        return memory

    @classmethod
    async def delete_memory(
        cls,
        db: AsyncSession,
        memory_id: uuid.UUID,
        user_id: uuid.UUID,
        hard_delete: bool = True,
    ) -> bool:
        """Delete a memory record ensuring user ownership (hard delete or soft archival)."""
        memory = await cls.get_memory_by_id(
            db=db, memory_id=memory_id, user_id=user_id, record_access=False
        )

        if hard_delete:
            await db.delete(memory)
        else:
            memory.status = MemoryStatus.ARCHIVED

        await db.flush()

        audit_logger.info(
            "AUDIT [MEMORY_DELETED] user_id=%s memory_id=%s hard_delete=%s",
            user_id,
            memory_id,
            hard_delete,
        )
        return True

    @classmethod
    async def apply_lifecycle_rules(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        retention_days: int = 30,
    ) -> LifecycleRuleResult:
        """Apply memory lifecycle rules: importance decay, access reinforcement, and archival."""
        now = datetime.now(UTC)
        cutoff_date = now - timedelta(days=retention_days)

        stmt = select(Memory).where(Memory.user_id == user_id, Memory.status == MemoryStatus.ACTIVE)
        res = await db.execute(stmt)
        memories = res.scalars().all()

        archived_count = 0
        decayed_count = 0
        reinforced_count = 0

        for mem in memories:
            # Rule 1: Reinforce frequently accessed memories
            if mem.access_count >= 5:
                boost = 0.05
                if mem.importance_score + boost <= 1.0:
                    mem.importance_score = round(mem.importance_score + boost, 3)
                    reinforced_count += 1

            # Rule 2: Preserve PREFERENCE and GOAL memories from aggressive decay
            if mem.memory_type in (MemoryType.PREFERENCE, MemoryType.GOAL):
                if mem.importance_score < 0.4:
                    mem.importance_score = 0.4
                continue

            # Rule 3: Decay stale, unaccessed EPISODIC memories
            created_utc = (
                mem.created_at
                if mem.created_at.tzinfo is not None
                else mem.created_at.replace(tzinfo=UTC)
            )
            if created_utc < cutoff_date and mem.access_count == 0:
                if mem.importance_score <= 0.2:
                    mem.status = MemoryStatus.ARCHIVED
                    archived_count += 1
                else:
                    mem.importance_score = round(max(0.1, mem.importance_score * 0.8), 3)
                    decayed_count += 1

        await db.flush()

        summary = (
            f"Lifecycle run complete: {reinforced_count} reinforced, {decayed_count} decayed, "
            f"{archived_count} archived."
        )
        audit_logger.info("AUDIT [MEMORY_LIFECYCLE_RUN] user_id=%s summary=%s", user_id, summary)

        return LifecycleRuleResult(
            archived_count=archived_count,
            decayed_count=decayed_count,
            reinforced_count=reinforced_count,
            summary=summary,
        )
