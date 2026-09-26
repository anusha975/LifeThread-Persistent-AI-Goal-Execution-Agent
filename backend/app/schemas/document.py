import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models.document import DocumentStatus


class DocumentChunkResponse(BaseModel):
    """Schema representing an extracted document text chunk."""

    id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID
    content: str
    chunk_index: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def extract_from_orm(cls, data: Any) -> Any:
        if hasattr(data, "metadata_json"):
            return {
                "id": data.id,
                "document_id": data.document_id,
                "user_id": data.user_id,
                "content": data.content,
                "chunk_index": data.chunk_index,
                "metadata": getattr(data, "metadata_json", {}) or {},
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            }
        return data


class DocumentResponse(BaseModel):
    """Schema representing an uploaded knowledge document."""

    id: uuid.UUID
    user_id: uuid.UUID
    filename: str
    content_type: str
    size: int
    checksum: str
    status: DocumentStatus
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def extract_from_orm(cls, data: Any) -> Any:
        if hasattr(data, "metadata_json"):
            return {
                "id": data.id,
                "user_id": data.user_id,
                "filename": data.filename,
                "content_type": data.content_type,
                "size": data.size,
                "checksum": data.checksum,
                "status": data.status,
                "error_message": getattr(data, "error_message", None),
                "metadata": getattr(data, "metadata_json", {}) or {},
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            }
        return data


class DocumentDetailResponse(DocumentResponse):
    """Document metadata along with its parsed chunks."""

    chunks: list[DocumentChunkResponse] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    items: list[DocumentResponse] = Field(default_factory=list)
    total: int = 0


class DocumentChunkListResponse(BaseModel):
    """Paginated list of document chunks."""

    items: list[DocumentChunkResponse] = Field(default_factory=list)
    total: int = 0


class DocumentUploadResult(BaseModel):
    """Result report from executing document ingestion."""

    document: DocumentResponse
    chunks: list[DocumentChunkResponse] = Field(default_factory=list)
    is_duplicate: bool = False
    message: str
