import uuid

import pytest
from app.db.base import Base
from app.db.models.document import Document, DocumentChunk, DocumentStatus
from app.services.document import DocumentService
from app.services.document_pipeline.chunker import TextChunker
from app.services.document_pipeline.cleaner import clean_text
from app.services.document_pipeline.errors import (
    DocumentExtractionError,
    DocumentValidationError,
)
from app.services.document_pipeline.pipeline import DocumentPipeline
from app.services.document_pipeline.security import sanitize_filename
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory() -> async_sessionmaker:
    """Create in-memory SQLite engine with fresh schema for Document Pipeline tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def make_pdf_bytes(text_lines: list[str]) -> bytes:
    """Helper to generate a real, valid PDF in memory using pymupdf."""
    import pymupdf

    doc = pymupdf.open()
    for text in text_lines:
        page = doc.new_page()
        page.insert_text((50, 50), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.mark.asyncio
async def test_txt_document_ingestion(session_factory: async_sessionmaker) -> None:
    """Requirement: Ingest plain text document, validate, clean, chunk, and store."""
    user_id = uuid.uuid4()
    content = (
        "LifeThread AI Agent architecture overview.\n\n"
        "The agent orchestrator observes state, decides next actions, "
        "and coordinates tool executions across the platform.\n\n"
        "Knowledge retrieval is supported by persistent memory and document intelligence."
    )
    raw_bytes = content.encode("utf-8")

    async with session_factory() as session:
        result = await DocumentService.ingest_document(
            db=session,
            user_id=user_id,
            filename="architecture_overview.txt",
            file_bytes=raw_bytes,
            chunk_size=150,
            chunk_overlap=20,
        )

        assert result.document.id is not None
        assert result.document.user_id == user_id
        assert result.document.filename == "architecture_overview.txt"
        assert result.document.content_type == "text/plain"
        assert result.document.size == len(raw_bytes)
        assert result.document.status == DocumentStatus.PROCESSED
        assert result.is_duplicate is False

        # Verify chunks created and linked to document and user
        assert len(result.chunks) >= 2
        for chunk in result.chunks:
            assert chunk.document_id == result.document.id
            assert chunk.user_id == user_id
            assert len(chunk.content) > 0


@pytest.mark.asyncio
async def test_markdown_document_ingestion(session_factory: async_sessionmaker) -> None:
    """Requirement: Ingest markdown document, preserve headings and code blocks."""
    user_id = uuid.uuid4()
    md_content = """# LifeThread API Guide

## 1. Authentication
Use JWT bearer tokens in the Authorization header.

```bash
curl -H "Authorization: Bearer <TOKEN>" https://api.lifethread.ai/v1/goals
```

## 2. Goals & Tasks
Goals represent high-level user ambitions decomposed into actionable tasks.
"""
    raw_bytes = md_content.encode("utf-8")

    async with session_factory() as session:
        result = await DocumentService.ingest_document(
            db=session,
            user_id=user_id,
            filename="api_guide.md",
            file_bytes=raw_bytes,
        )

        assert result.document.status == DocumentStatus.PROCESSED
        assert result.document.content_type == "text/markdown"
        assert result.document.metadata["extractor"]["heading_count"] == 3
        assert result.document.metadata["extractor"]["code_block_count"] == 1
        assert len(result.chunks) >= 1


@pytest.mark.asyncio
async def test_pdf_document_ingestion(session_factory: async_sessionmaker) -> None:
    """Requirement: Ingest real PDF document, parse pages, clean, and chunk."""
    user_id = uuid.uuid4()
    pdf_bytes = make_pdf_bytes(
        [
            "Page 1: Deep reinforcement learning principles in LifeThread agents.",
            "Page 2: Evaluation metrics and performance tracking under strict deadlines.",
        ]
    )

    async with session_factory() as session:
        result = await DocumentService.ingest_document(
            db=session,
            user_id=user_id,
            filename="research_paper.pdf",
            file_bytes=pdf_bytes,
        )

        assert result.document.status == DocumentStatus.PROCESSED
        assert result.document.content_type == "application/pdf"
        assert result.document.metadata["extractor"]["page_count"] == 2
        assert len(result.chunks) >= 1
        assert "Deep reinforcement learning" in result.chunks[0].content


@pytest.mark.asyncio
async def test_file_size_limits(session_factory: async_sessionmaker) -> None:
    """Requirement: Enforce file size limits and reject empty documents."""
    user_id = uuid.uuid4()
    pipeline = DocumentPipeline(max_file_size_bytes=100)

    async with session_factory() as session:
        # 1. Empty file
        with pytest.raises(DocumentValidationError) as exc_info:
            await pipeline.ingest_document(
                db=session,
                user_id=user_id,
                filename="empty.txt",
                file_bytes=b"",
            )
        assert "empty" in str(exc_info.value).lower()

        # 2. Exceeds max boundary (100 bytes limit vs 200 bytes payload)
        large_bytes = b"A" * 200
        with pytest.raises(DocumentValidationError) as exc_info:
            await pipeline.ingest_document(
                db=session,
                user_id=user_id,
                filename="large.txt",
                file_bytes=large_bytes,
            )
        assert "exceeds maximum allowed size" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_type_validation_and_content_sniffing(
    session_factory: async_sessionmaker,
) -> None:
    """Requirement: Validate content type and detect mismatched magic bytes."""
    user_id = uuid.uuid4()
    pipeline = DocumentPipeline()

    async with session_factory() as session:
        # 1. Unsupported extension (.exe)
        with pytest.raises(DocumentValidationError) as exc_info:
            await pipeline.ingest_document(
                db=session,
                user_id=user_id,
                filename="malware.exe",
                file_bytes=b"MZ\x90\x00executable",
            )
        assert "unsupported file type" in str(exc_info.value).lower()

        # 2. Fake PDF (extension .pdf but missing %PDF- header)
        fake_pdf = b"This is just plain text disguised as a PDF document."
        with pytest.raises(DocumentValidationError) as exc_info:
            await pipeline.ingest_document(
                db=session,
                user_id=user_id,
                filename="fake.pdf",
                file_bytes=fake_pdf,
            )
        assert "missing '%pdf-'" in str(exc_info.value).lower()

        # 3. Binary executable masquerading as a .txt file (contains null bytes)
        fake_txt = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff"
        with pytest.raises(DocumentValidationError) as exc_info:
            await pipeline.ingest_document(
                db=session,
                user_id=user_id,
                filename="fake.txt",
                file_bytes=fake_txt,
            )
        assert "binary content detected" in str(exc_info.value).lower()


def test_secure_filename_sanitization() -> None:
    """Requirement: Secure filenames against path traversal, control chars, and shell attacks."""
    # Path traversal attack
    assert sanitize_filename("../../../etc/passwd.txt") == "passwd.txt"
    assert sanitize_filename("..\\..\\windows\\system32\\cmd.exe.txt") == "cmd_exe.txt"

    # Control chars and special characters
    assert sanitize_filename("my\x00bad\x1fname;rm -rf.txt") == "mybadname_rm_-rf.txt"

    # Excessively long filename
    long_name = "a" * 300 + ".pdf"
    sanitized = sanitize_filename(long_name)
    assert len(sanitized) <= 200
    assert sanitized.endswith(".pdf")


@pytest.mark.asyncio
async def test_duplicate_detection_and_user_isolation(
    session_factory: async_sessionmaker,
) -> None:
    """Requirement: Detect duplicates per user while allowing identical uploads across users."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    sample_bytes = b"Standard operating procedures for LifeThread tasks."

    async with session_factory() as session:
        # User A uploads doc
        res_a1 = await DocumentService.ingest_document(
            db=session,
            user_id=user_a,
            filename="sop.txt",
            file_bytes=sample_bytes,
        )
        assert res_a1.is_duplicate is False

        # User A re-uploads identical document -> duplicate detected
        res_a2 = await DocumentService.ingest_document(
            db=session,
            user_id=user_a,
            filename="sop_copy.txt",
            file_bytes=sample_bytes,
        )
        assert res_a2.is_duplicate is True
        assert res_a2.document.id == res_a1.document.id

        # User B uploads the same document -> succeeds independently (no cross-user collision)
        res_b = await DocumentService.ingest_document(
            db=session,
            user_id=user_b,
            filename="sop.txt",
            file_bytes=sample_bytes,
        )
        assert res_b.is_duplicate is False
        assert res_b.document.id != res_a1.document.id
        assert res_b.document.user_id == user_b


@pytest.mark.asyncio
async def test_extraction_error_handling(session_factory: async_sessionmaker) -> None:
    """Requirement: Graceful handling of corrupted files, status=FAILED recorded."""
    user_id = uuid.uuid4()
    # Has %PDF- header to pass type validation, but corrupted stream
    corrupt_pdf = b"%PDF-1.4\nCorrupted stream data with no catalog or trailer xref"

    async with session_factory() as session:
        with pytest.raises(DocumentExtractionError):
            await DocumentService.ingest_document(
                db=session,
                user_id=user_id,
                filename="corrupted.pdf",
                file_bytes=corrupt_pdf,
            )

        # Verify failed document record was persisted for audit/observability
        stmt = select(Document).where(
            Document.user_id == user_id, Document.status == DocumentStatus.FAILED
        )
        res = await session.execute(stmt)
        failed_doc = res.scalar_one_or_none()

        assert failed_doc is not None
        assert failed_doc.filename == "corrupted.pdf"
        assert failed_doc.status == DocumentStatus.FAILED
        assert failed_doc.error_message is not None


@pytest.mark.asyncio
async def test_strict_user_isolation(session_factory: async_sessionmaker) -> None:
    """Acceptance Criteria & Requirement: Strict user isolation for documents and chunks."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    async with session_factory() as session:
        doc_a = await DocumentService.ingest_document(
            db=session,
            user_id=user_a,
            filename="user_a_private.txt",
            file_bytes=b"Confidential user A journal entries.",
        )

        # User A can get their document and chunks
        got_a = await DocumentService.get_document(
            db=session, document_id=doc_a.document.id, user_id=user_a
        )
        assert got_a.id == doc_a.document.id

        chunks_a, total_a = await DocumentService.get_document_chunks(
            db=session, document_id=doc_a.document.id, user_id=user_a
        )
        assert total_a >= 1

        # User B cannot access User A's document (raises 404)
        with pytest.raises(HTTPException) as exc_info:
            await DocumentService.get_document(
                db=session, document_id=doc_a.document.id, user_id=user_b
            )
        assert exc_info.value.status_code == 404

        # User B cannot access User A's chunks (raises 404)
        with pytest.raises(HTTPException) as exc_info:
            await DocumentService.get_document_chunks(
                db=session, document_id=doc_a.document.id, user_id=user_b
            )
        assert exc_info.value.status_code == 404

        # User B listing returns 0 documents
        b_docs, b_total = await DocumentService.list_documents(db=session, user_id=user_b)
        assert b_total == 0
        assert len(b_docs) == 0


@pytest.mark.asyncio
async def test_document_deletion_cascades_chunks(
    session_factory: async_sessionmaker,
) -> None:
    """Requirement: Deleting a document cascades and removes all chunks."""
    user_id = uuid.uuid4()

    async with session_factory() as session:
        res = await DocumentService.ingest_document(
            db=session,
            user_id=user_id,
            filename="to_delete.txt",
            file_bytes=b"Text content that will be deleted along with all its chunks.",
        )
        doc_id = res.document.id

        # Verify chunks exist in DB
        chunk_stmt = select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        chunks_before = (await session.execute(chunk_stmt)).scalars().all()
        assert len(chunks_before) >= 1

        # Delete document
        deleted = await DocumentService.delete_document(
            db=session, document_id=doc_id, user_id=user_id
        )
        assert deleted is True

        # Verify document is gone
        with pytest.raises(HTTPException) as exc_info:
            await DocumentService.get_document(db=session, document_id=doc_id, user_id=user_id)
        assert exc_info.value.status_code == 404

        # Verify chunks were cascade deleted
        chunks_after = (await session.execute(chunk_stmt)).scalars().all()
        assert len(chunks_after) == 0


def test_text_cleaner_and_chunker_behavior() -> None:
    """Requirement: Test cleaning (null bytes, repeated newlines) and chunking with overlap."""
    dirty_text = "Line 1\x00\x08with control chars.\r\n\r\n\r\n\r\nLine 2 with trailing spaces.   \n\nLine 3."
    cleaned = clean_text(dirty_text)

    assert "\x00" not in cleaned
    assert "\r" not in cleaned
    assert "\n\n\n" not in cleaned  # Max 2 consecutive newlines
    assert "Line 1with control chars." in cleaned

    # Chunker test
    chunker = TextChunker(chunk_size=50, chunk_overlap=10)
    sample_text = (
        "The quick brown fox jumps over the lazy dog. "
        "Artificial intelligence powers LifeThread autonomous execution engine. "
        "Goals are parsed into milestones, tasks, and dependencies."
    )
    chunks = chunker.chunk_text(sample_text)
    assert len(chunks) >= 2

    # Check contiguous indexing and metadata
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert c.metadata["chunk_index"] == i
        assert c.char_start >= 0
        assert c.char_end > c.char_start
