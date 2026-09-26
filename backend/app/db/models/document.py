import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.models.base import BaseDBModel

if TYPE_CHECKING:
    from app.db.models.user import User


class DocumentStatus(StrEnum):
    """Lifecycle statuses for an uploaded knowledge document."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class Document(BaseDBModel):
    """Uploaded knowledge document entity for RAG processing."""

    __tablename__ = "documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner user ID for strict multi-tenant isolation",
    )
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Sanitized original filename of the uploaded document",
    )
    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Validated MIME content type (e.g. application/pdf, text/plain, text/markdown)",
    )
    size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        doc="Document file size in bytes",
    )
    checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="SHA-256 content checksum for duplicate detection",
    )
    status: Mapped[DocumentStatus] = mapped_column(
        SQLAlchemyEnum(DocumentStatus, native_enum=False, length=50),
        nullable=False,
        default=DocumentStatus.PENDING,
        index=True,
        doc="Processing status: PENDING, PROCESSING, PROCESSED, FAILED",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Extraction or processing error message if status is FAILED",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Arbitrary structured metadata (e.g. page_count, chunk_count, token_estimate)",
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="documents",
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
    )


class DocumentChunk(BaseDBModel):
    """Granular text chunk extracted from a document for RAG indexing."""

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Parent document ID",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner user ID for strict multi-tenant isolation",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Cleaned textual chunk content",
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        doc="Sequential zero-based index of this chunk within the parent document",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Chunk-level metadata (e.g. char offsets, token estimate, page number)",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536),
        nullable=True,
        doc="1536-dimensional semantic vector embedding for chunk retrieval",
    )

    # Relationship
    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="chunks",
    )
