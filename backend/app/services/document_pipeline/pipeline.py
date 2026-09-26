import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document, DocumentChunk, DocumentStatus
from app.schemas.document import (
    DocumentChunkResponse,
    DocumentResponse,
    DocumentUploadResult,
)
from app.services.document_pipeline.chunker import TextChunker
from app.services.document_pipeline.cleaner import clean_text
from app.services.document_pipeline.errors import (
    DocumentExtractionError,
)
from app.services.document_pipeline.extractors.factory import get_extractor
from app.services.document_pipeline.security import (
    compute_checksum,
    detect_and_validate_mime,
    sanitize_filename,
    validate_file_size,
)
from app.services.embeddings.base import BaseEmbeddingProvider

logger = logging.getLogger("lifethread.pipeline.document")
audit_logger = logging.getLogger("lifethread.audit.document")


class DocumentPipeline:
    """Document Intelligence Pipeline orchestrating:

    Upload -> validation -> extraction -> cleaning -> chunking -> metadata -> storage.
    """

    def __init__(
        self,
        default_chunk_size: int = 500,
        default_chunk_overlap: int = 50,
        max_file_size_bytes: int = 15 * 1024 * 1024,
    ) -> None:
        self.default_chunk_size = default_chunk_size
        self.default_chunk_overlap = default_chunk_overlap
        self.max_file_size_bytes = max_file_size_bytes

    async def check_duplicate(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        checksum: str,
    ) -> Document | None:
        """Detect if an identical document checksum already exists for this user."""
        stmt = select(Document).where(
            Document.user_id == user_id,
            Document.checksum == checksum,
            Document.status == DocumentStatus.PROCESSED,
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    async def ingest_document(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        filename: str,
        file_bytes: bytes,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        allow_duplicate: bool = False,
        embedding_provider: BaseEmbeddingProvider | None = None,
    ) -> DocumentUploadResult:
        """Execute the end-to-end document intelligence ingestion pipeline."""
        c_size = chunk_size or self.default_chunk_size
        c_overlap = chunk_overlap if chunk_overlap is not None else self.default_chunk_overlap

        # 1. Validation (File size limits, secure filename, type validation, checksum)
        validate_file_size(len(file_bytes), max_bytes=self.max_file_size_bytes)
        sanitized_name = sanitize_filename(filename)
        content_type = detect_and_validate_mime(file_bytes, sanitized_name)
        checksum = compute_checksum(file_bytes)

        # 2. Duplicate Detection (Per user isolation)
        existing_doc = await self.check_duplicate(db=db, user_id=user_id, checksum=checksum)
        if existing_doc is not None and not allow_duplicate:
            audit_logger.info(
                "AUDIT [DOCUMENT_DUPLICATE_DETECTED] user_id=%s document_id=%s checksum=%s filename=%s",
                user_id,
                existing_doc.id,
                checksum,
                sanitized_name,
            )
            # Fetch existing chunks
            chunk_stmt = (
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == existing_doc.id,
                    DocumentChunk.user_id == user_id,
                )
                .order_by(DocumentChunk.chunk_index)
            )
            chunks_res = await db.execute(chunk_stmt)
            existing_chunks = chunks_res.scalars().all()

            return DocumentUploadResult(
                document=DocumentResponse.model_validate(existing_doc),
                chunks=[DocumentChunkResponse.model_validate(c) for c in existing_chunks],
                is_duplicate=True,
                message=f"Duplicate document detected (matches existing document '{existing_doc.filename}')",
            )

        # 3. Text Extraction with Error Handling
        extractor = get_extractor(content_type)
        try:
            raw_text, extractor_meta = extractor.extract(file_bytes, sanitized_name)
        except DocumentExtractionError as e:
            logger.error("Document extraction failed for '%s': %s", sanitized_name, e)
            # Create failed document record for observability
            failed_doc = Document(
                user_id=user_id,
                filename=sanitized_name,
                content_type=content_type,
                size=len(file_bytes),
                checksum=checksum,
                status=DocumentStatus.FAILED,
                error_message=str(e),
                metadata_json={
                    "original_filename": filename,
                    "error": str(e),
                },
            )
            db.add(failed_doc)
            await db.flush()
            await db.refresh(failed_doc)

            audit_logger.warning(
                "AUDIT [DOCUMENT_EXTRACTION_FAILED] user_id=%s document_id=%s error=%s",
                user_id,
                failed_doc.id,
                str(e),
            )
            raise

        # 4. Text Cleaning
        cleaned_text = clean_text(raw_text)

        # 5. Chunking
        chunker = TextChunker(chunk_size=c_size, chunk_overlap=c_overlap)
        chunk_items = chunker.chunk_text(cleaned_text)

        # 6. Metadata Compilation
        doc_metadata: dict[str, Any] = {
            "original_filename": filename,
            "sanitized_filename": sanitized_name,
            "char_count": len(cleaned_text),
            "chunk_count": len(chunk_items),
            "chunk_size": c_size,
            "chunk_overlap": c_overlap,
            "extractor": extractor_meta,
        }

        # 7. Embedding Generation for Chunks (Requirement 1 & 2)
        chunk_embeddings: list[list[float] | None] = [None] * len(chunk_items)
        if embedding_provider is not None and chunk_items:
            try:
                chunk_embeddings = await embedding_provider.generate_embeddings(
                    [item.content for item in chunk_items]
                )
            except Exception as e:
                logger.warning(
                    "Embedding generation failed for document '%s': %s. Continuing storage without embeddings.",
                    sanitized_name,
                    e,
                )
                audit_logger.warning(
                    "AUDIT [DOCUMENT_CHUNK_EMBEDDING_FAILED] user_id=%s document=%s error=%s",
                    user_id,
                    sanitized_name,
                    str(e),
                )
                chunk_embeddings = [None] * len(chunk_items)

        # 8. Database Persistence (Atomic Document + DocumentChunks with pgvector embeddings)
        doc = Document(
            user_id=user_id,
            filename=sanitized_name,
            content_type=content_type,
            size=len(file_bytes),
            checksum=checksum,
            status=DocumentStatus.PROCESSED,
            metadata_json=doc_metadata,
        )
        db.add(doc)
        await db.flush()
        await db.refresh(doc)

        created_chunks: list[DocumentChunk] = []
        for i, item in enumerate(chunk_items):
            chunk_meta = dict(item.metadata)
            chunk_meta.update(
                {
                    "document_id": str(doc.id),
                    "filename": sanitized_name,
                    "content_type": content_type,
                }
            )
            emb = chunk_embeddings[i] if i < len(chunk_embeddings) else None
            chunk = DocumentChunk(
                document_id=doc.id,
                user_id=user_id,
                content=item.content,
                chunk_index=item.chunk_index,
                metadata_json=chunk_meta,
                embedding=emb,
            )
            db.add(chunk)
            created_chunks.append(chunk)

        await db.flush()
        for chunk in created_chunks:
            await db.refresh(chunk)

        audit_logger.info(
            "AUDIT [DOCUMENT_INGESTED] user_id=%s document_id=%s filename=%s type=%s size=%d chunks=%d",
            user_id,
            doc.id,
            sanitized_name,
            content_type,
            len(file_bytes),
            len(created_chunks),
        )

        return DocumentUploadResult(
            document=DocumentResponse.model_validate(doc),
            chunks=[DocumentChunkResponse.model_validate(c) for c in created_chunks],
            is_duplicate=False,
            message="Document successfully processed and chunked.",
        )
