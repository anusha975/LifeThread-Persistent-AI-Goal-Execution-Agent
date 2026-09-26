import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document, DocumentChunk, DocumentStatus
from app.schemas.document import DocumentUploadResult
from app.services.document_pipeline.pipeline import DocumentPipeline
from app.services.embeddings.base import BaseEmbeddingProvider

logger = logging.getLogger("lifethread.services.document")
audit_logger = logging.getLogger("lifethread.audit.document")


class DocumentService:
    """Core domain service for knowledge document management and retrieval with user isolation."""

    @classmethod
    async def ingest_document(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        filename: str,
        file_bytes: bytes,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        allow_duplicate: bool = False,
        embedding_provider: BaseEmbeddingProvider | None = None,
    ) -> DocumentUploadResult:
        """Process and ingest a document through the document intelligence pipeline."""
        pipeline = DocumentPipeline()
        return await pipeline.ingest_document(
            db=db,
            user_id=user_id,
            filename=filename,
            file_bytes=file_bytes,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            allow_duplicate=allow_duplicate,
            embedding_provider=embedding_provider,
        )

    @classmethod
    async def get_document(
        cls,
        db: AsyncSession,
        document_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Document:
        """Retrieve a specific document enforcing strict user ownership and detecting IDOR attempts."""
        from app.db.access_control import DatabaseAccessControl

        return await DatabaseAccessControl.get_user_resource_or_404(
            db=db,
            model=Document,
            resource_id=document_id,
            user_id=user_id,
            resource_name="document",
        )

    @classmethod
    async def list_documents(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        status_filter: DocumentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        """List documents owned by the user with pagination and optional status filter."""
        stmt = select(Document).where(Document.user_id == user_id)
        count_stmt = select(func.count(Document.id)).where(Document.user_id == user_id)

        if status_filter is not None:
            stmt = stmt.where(Document.status == status_filter)
            count_stmt = count_stmt.where(Document.status == status_filter)

        count_res = await db.execute(count_stmt)
        total = count_res.scalar() or 0

        stmt = stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)
        res = await db.execute(stmt)
        docs = list(res.scalars().all())

        return docs, total

    @classmethod
    async def get_document_chunks(
        cls,
        db: AsyncSession,
        document_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[DocumentChunk], int]:
        """Retrieve chunks for a document enforcing user ownership on document and chunks."""
        # 1. Verify document ownership
        await cls.get_document(db=db, document_id=document_id, user_id=user_id)

        # 2. Query chunks scoped to document_id AND user_id
        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.user_id == user_id,
            )
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count(DocumentChunk.id)).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.user_id == user_id,
        )

        count_res = await db.execute(count_stmt)
        total = count_res.scalar() or 0

        res = await db.execute(stmt)
        chunks = list(res.scalars().all())

        return chunks, total

    @classmethod
    async def delete_document(
        cls,
        db: AsyncSession,
        document_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Delete a document and all its chunks with cascade deletion."""
        doc = await cls.get_document(db=db, document_id=document_id, user_id=user_id)
        await db.delete(doc)
        await db.flush()

        audit_logger.info(
            "AUDIT [DOCUMENT_DELETED] user_id=%s document_id=%s filename=%s",
            user_id,
            document_id,
            doc.filename,
        )
        return True
