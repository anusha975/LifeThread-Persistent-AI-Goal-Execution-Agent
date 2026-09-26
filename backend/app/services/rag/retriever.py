import logging
import math
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document, DocumentChunk
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.factory import get_embedding_provider
from app.services.rag.models import RetrievedChunk

logger = logging.getLogger("lifethread.rag.retriever")
audit_logger = logging.getLogger("lifethread.audit.rag.retriever")


class Retriever:
    """Retrieves relevant document chunks using pgvector semantic similarity search,

    metadata filtering, and strict multi-tenant isolation.
    """

    def __init__(self, embedding_provider: BaseEmbeddingProvider | None = None) -> None:
        self.embedding_provider = embedding_provider or get_embedding_provider()

    @staticmethod
    def _cosine_similarity(vec_a: list[float] | Any, vec_b: list[float]) -> tuple[float, float]:
        """Calculate cosine similarity and distance between two vectors."""
        v_a = [float(x) for x in vec_a]
        v_b = [float(x) for x in vec_b]

        dot = sum(a * b for a, b in zip(v_a, v_b, strict=False))
        norm_a = math.sqrt(sum(a * a for a in v_a))
        norm_b = math.sqrt(sum(b * b for b in v_b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0, 1.0

        sim = dot / (norm_a * norm_b)
        sim = max(-1.0, min(1.0, sim))
        dist = max(0.0, 1.0 - sim)
        return round(sim, 4), round(dist, 4)

    @staticmethod
    def _matches_metadata(
        metadata_json: dict[str, Any] | None, filter_dict: dict[str, Any] | None
    ) -> bool:
        """Check if metadata satisfies all filter conditions."""
        if not filter_dict:
            return True
        if not metadata_json:
            return False

        for k, expected in filter_dict.items():
            if k not in metadata_json:
                return False
            actual = metadata_json[k]
            if isinstance(expected, list):
                if isinstance(actual, list):
                    if not any(item in actual for item in expected):
                        return False
                elif actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    async def retrieve(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.0,
        metadata_filter: dict[str, Any] | None = None,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[RetrievedChunk]:
        """Execute semantic vector retrieval over document chunks with strict user isolation."""
        clean_query = query.strip()
        if not clean_query:
            return []

        # 1. Generate query embedding
        query_embedding = await self.embedding_provider.generate_embedding(clean_query)

        # 2. Database query with strict user isolation
        bind = db.bind
        dialect_name = bind.dialect.name if bind else "postgresql"

        candidate_results: list[tuple[DocumentChunk, str, float, float]] = []

        if dialect_name == "postgresql":
            # PostgreSQL native pgvector distance
            distance_col = DocumentChunk.embedding.cosine_distance(query_embedding).label(
                "distance"
            )
            stmt = (
                select(DocumentChunk, Document.filename, distance_col)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.user_id == user_id,
                    DocumentChunk.embedding.is_not(None),
                )
            )
            if document_ids:
                stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))

            stmt = stmt.order_by(distance_col.asc())
            rows = (await db.execute(stmt)).all()

            for chunk, filename, dist in rows:
                dist_val = float(dist)
                sim_val = round(max(-1.0, min(1.0, 1.0 - dist_val)), 4)
                candidate_results.append((chunk, filename, sim_val, round(dist_val, 4)))
        else:
            # SQLite / Test fallback
            stmt = (
                select(DocumentChunk, Document.filename)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.user_id == user_id,
                    DocumentChunk.embedding.is_not(None),
                )
            )
            if document_ids:
                stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))

            rows = (await db.execute(stmt)).all()
            for chunk, filename in rows:
                if chunk.embedding is None:
                    continue
                sim, dist = self._cosine_similarity(chunk.embedding, query_embedding)
                candidate_results.append((chunk, filename, sim, dist))

        # 3. Metadata Filtering
        filtered_candidates: list[tuple[DocumentChunk, str, float, float]] = []
        for chunk, filename, sim, dist in candidate_results:
            if metadata_filter and not self._matches_metadata(chunk.metadata_json, metadata_filter):
                continue
            filtered_candidates.append((chunk, filename, sim, dist))

        # 4. Similarity Threshold
        thresholded: list[tuple[DocumentChunk, str, float, float]] = []
        for chunk, filename, sim, dist in filtered_candidates:
            if sim >= similarity_threshold:
                thresholded.append((chunk, filename, sim, dist))

        # 5. Order by similarity descending, slice top_k
        thresholded.sort(key=lambda item: (-item[2], item[3]))
        top_slice = thresholded[:top_k]

        # 6. Build RetrievedChunk objects
        results: list[RetrievedChunk] = []
        for chunk, filename, sim, dist in top_slice:
            page_num = chunk.metadata_json.get("page_number")
            results.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    user_id=chunk.user_id,
                    filename=filename,
                    content=chunk.content,
                    chunk_index=chunk.chunk_index,
                    metadata=chunk.metadata_json or {},
                    similarity_score=sim,
                    distance=dist,
                    page_number=page_num,
                )
            )

        audit_logger.info(
            "AUDIT [RAG_RETRIEVAL] user_id=%s query='%s' candidates=%d returned=%d top_k=%d",
            user_id,
            clean_query[:50],
            len(candidate_results),
            len(results),
            top_k,
        )

        return results
