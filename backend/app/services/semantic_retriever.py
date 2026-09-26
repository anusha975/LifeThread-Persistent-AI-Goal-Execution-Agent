import logging
import math
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory import Memory, MemoryStatus, MemoryType
from app.schemas.memory import MemoryResponse, SemanticSearchResult
from app.services.embeddings.base import (
    BaseEmbeddingProvider,
    EmbeddingGenerationError,
)
from app.services.embeddings.factory import get_embedding_provider

logger = logging.getLogger("lifethread.services.semantic_retriever")
audit_logger = logging.getLogger("lifethread.audit.semantic_retriever")


class SemanticMemoryRetriever:
    """Retriever for pgvector-backed semantic memory retrieval with metadata filtering,

    similarity thresholding, top-k ranking, and strict tenant isolation.
    """

    _embedding_cache: dict[str, list[float]] = {}
    _cache_max_size: int = 1024

    def __init__(
        self,
        embedding_provider: BaseEmbeddingProvider | None = None,
        default_top_k: int = 5,
        default_similarity_threshold: float | None = None,
    ) -> None:
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.default_top_k = default_top_k
        self.default_similarity_threshold = default_similarity_threshold

    @classmethod
    def _cosine_similarity_and_distance(
        cls,
        vec_a: list[float] | Any,
        vec_b: list[float],
        norm_b: float | None = None,
    ) -> tuple[float, float]:
        """Compute cosine similarity and distance between vectors with optional precomputed norm."""
        dot = 0.0
        sum_sq_a = 0.0
        for a, b in zip(vec_a, vec_b, strict=False):
            fa = float(a)
            fb = float(b)
            dot += fa * fb
            sum_sq_a += fa * fa

        if sum_sq_a == 0.0:
            return 0.0, 1.0

        norm_a = math.sqrt(sum_sq_a)
        if norm_b is None:
            norm_b = math.sqrt(sum(float(x) * float(x) for x in vec_b))

        if norm_b == 0.0:
            return 0.0, 1.0

        sim = dot / (norm_a * norm_b)
        sim = max(-1.0, min(1.0, sim))
        dist = max(0.0, 1.0 - sim)
        return round(sim, 4), round(dist, 4)

    @staticmethod
    def _matches_metadata(
        metadata_json: dict[str, Any] | None, filter_dict: dict[str, Any] | None
    ) -> bool:
        """Check if metadata dictionary satisfies all filter conditions."""
        if not filter_dict:
            return True
        if not metadata_json:
            return False

        for key, expected_val in filter_dict.items():
            if key not in metadata_json:
                return False
            actual_val = metadata_json[key]
            if isinstance(expected_val, list):
                if isinstance(actual_val, list):
                    if not any(item in actual_val for item in expected_val):
                        return False
                elif actual_val not in expected_val:
                    return False
            elif actual_val != expected_val:
                return False
        return True

    async def retrieve(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        query: str,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        memory_type: MemoryType | None = None,
        metadata_filter: dict[str, Any] | None = None,
        source: str | None = None,
        status: MemoryStatus | None = MemoryStatus.ACTIVE,
    ) -> list[SemanticSearchResult]:
        """Execute semantic vector retrieval workflow:

        Query -> embedding -> vector search -> metadata filtering -> similarity threshold -> ranked memories.
        Strictly guarantees multi-tenant isolation by scoping to user_id.
        """
        k = top_k if top_k is not None else self.default_top_k
        threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.default_similarity_threshold
        )

        stripped_query = query.strip()
        if not stripped_query:
            return []

        # 1. Query -> Embedding (Generate query vector with failure handling & caching)
        cache_key = f"{self.embedding_provider.__class__.__name__}:{stripped_query}"
        if cache_key in self._embedding_cache:
            query_embedding = self._embedding_cache[cache_key]
        else:
            try:
                query_embedding = await self.embedding_provider.generate_embedding(stripped_query)
                if len(self._embedding_cache) >= self._cache_max_size:
                    self._embedding_cache.pop(next(iter(self._embedding_cache)))
                self._embedding_cache[cache_key] = query_embedding
            except Exception as e:
                logger.error("Failed to generate query embedding for user %s: %s", user_id, e)
                audit_logger.warning(
                    "AUDIT [SEMANTIC_QUERY_EMBEDDING_FAILED] user_id=%s query=%s error=%s",
                    user_id,
                    stripped_query,
                    str(e),
                )
                if isinstance(e, EmbeddingGenerationError):
                    raise
                raise EmbeddingGenerationError(
                    f"Failed to generate embedding for query: {e!s}", original_error=e
                ) from e

        # 2. Vector search & candidates retrieval with strict user isolation
        bind = db.bind
        dialect_name = bind.dialect.name if bind else "postgresql"

        candidate_results: list[tuple[Memory, float, float]] = []

        if dialect_name == "postgresql":
            # Native pgvector cosine distance: distance = 1 - cosine_similarity
            distance_col = Memory.embedding.cosine_distance(query_embedding).label("distance")
            pg_stmt = select(Memory, distance_col).where(
                Memory.user_id == user_id,
                Memory.embedding.is_not(None),
            )
            if status is not None:
                pg_stmt = pg_stmt.where(Memory.status == status)
            if memory_type is not None:
                pg_stmt = pg_stmt.where(Memory.memory_type == memory_type)
            if source is not None:
                pg_stmt = pg_stmt.where(Memory.source == source)

            pg_stmt = pg_stmt.order_by(distance_col.asc())
            result = await db.execute(pg_stmt)
            rows = result.all()

            for memory, dist in rows:
                dist_val = float(dist)
                sim_val = round(max(-1.0, min(1.0, 1.0 - dist_val)), 4)
                candidate_results.append((memory, sim_val, round(dist_val, 4)))
        else:
            # SQLite / fallback dialect with optimized cosine similarity
            stmt = select(Memory).where(
                Memory.user_id == user_id,
                Memory.embedding.is_not(None),
            )
            if status is not None:
                stmt = stmt.where(Memory.status == status)
            if memory_type is not None:
                stmt = stmt.where(Memory.memory_type == memory_type)
            if source is not None:
                stmt = stmt.where(Memory.source == source)

            result = await db.execute(stmt)
            memories = result.scalars().all()

            query_norm = math.sqrt(sum(float(x) * float(x) for x in query_embedding))
            for mem in memories:
                if mem.embedding is None:
                    continue
                sim, dist = self._cosine_similarity_and_distance(mem.embedding, query_embedding, norm_b=query_norm)
                candidate_results.append((mem, sim, dist))

        # 3. Metadata filtering
        filtered_candidates: list[tuple[Memory, float, float]] = []
        for mem, sim, dist in candidate_results:
            if metadata_filter and not self._matches_metadata(mem.metadata_json, metadata_filter):
                continue
            filtered_candidates.append((mem, sim, dist))

        # 4. Similarity threshold filtering
        thresholded_candidates: list[tuple[Memory, float, float]] = []
        for mem, sim, dist in filtered_candidates:
            if threshold is not None and sim < threshold:
                continue
            thresholded_candidates.append((mem, sim, dist))

        # 5. Ranked memories (Rank by similarity_score DESC, distance ASC, slice top_k)
        thresholded_candidates.sort(key=lambda item: (-item[1], item[2]))
        top_ranked = thresholded_candidates[:k]

        # 6. Format structured results (preserving original memory text intact)
        results: list[SemanticSearchResult] = []
        for mem, sim, dist in top_ranked:
            mem_resp = MemoryResponse.model_validate(mem)
            results.append(
                SemanticSearchResult(
                    memory=mem_resp,
                    similarity_score=sim,
                    distance=dist,
                )
            )

        audit_logger.info(
            "AUDIT [SEMANTIC_MEMORY_RETRIEVAL] user_id=%s query=%s candidates=%d matched=%d top_k=%d threshold=%.2f",
            user_id,
            stripped_query,
            len(candidate_results),
            len(results),
            k,
            threshold,
        )

        return results
