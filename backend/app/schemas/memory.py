import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models.memory import MemoryStatus, MemoryType


class MemoryCreate(BaseModel):
    """Schema for creating a new persistent memory record."""

    content: str = Field(..., min_length=1, description="Memory text content or observation")
    memory_type: MemoryType = Field(
        default=MemoryType.EPISODIC,
        description="Memory category: EPISODIC, SEMANTIC, GOAL, PREFERENCE",
    )
    importance_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Importance score ranging from 0.0 (lowest) to 1.0 (critical)",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence or certainty score between 0.0 and 1.0",
    )
    source: str = Field(
        default="agent",
        min_length=1,
        max_length=255,
        description="Provenance of the memory (e.g. agent, user, observation, tool, reflection)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured arbitrary metadata dictionary",
    )
    deduplicate: bool = Field(
        default=True,
        description="Whether to perform duplicate detection and reinforcement on creation",
    )

    @field_validator("content")
    @classmethod
    def validate_content_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Memory content cannot be empty or whitespace only")
        return stripped


class MemoryUpdate(BaseModel):
    """Schema for updating an existing memory record."""

    content: str | None = Field(default=None, min_length=1, description="Updated memory text")
    memory_type: MemoryType | None = Field(default=None, description="Updated memory category")
    importance_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Updated importance score (0.0 to 1.0)",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Updated confidence score (0.0 to 1.0)",
    )
    source: str | None = Field(
        default=None, min_length=1, max_length=255, description="Updated source"
    )
    status: MemoryStatus | None = Field(
        default=None, description="Updated lifecycle state (ACTIVE, ARCHIVED, SUPERSEDED)"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Updated metadata dictionary (replaces or merges)"
    )

    @field_validator("content")
    @classmethod
    def validate_content_non_empty(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("Memory content cannot be empty or whitespace only")
            return stripped
        return v


class MemoryFilterParams(BaseModel):
    """Structured filtering parameters for querying memory records."""

    query: str | None = Field(default=None, description="Text substring filter on content")
    memory_type: MemoryType | None = Field(default=None, description="Filter by memory type")
    min_importance: float | None = Field(default=None, ge=0.0, le=1.0)
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str | None = Field(default=None, description="Filter by provenance source")
    status: MemoryStatus | None = Field(
        default=MemoryStatus.ACTIVE, description="Filter by lifecycle status"
    )
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class MemoryResponse(BaseModel):
    """Schema for returning a memory entity."""

    id: uuid.UUID
    user_id: uuid.UUID
    memory_type: MemoryType
    type: MemoryType | None = None
    content: str
    source: str
    importance_score: float
    importance: float | None = None
    confidence: float = 1.0
    status: MemoryStatus = MemoryStatus.ACTIVE
    access_count: int = 0
    last_accessed_at: datetime | None = None
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
                "memory_type": data.memory_type,
                "type": data.memory_type,
                "content": data.content,
                "source": data.source,
                "importance_score": data.importance_score,
                "importance": data.importance_score,
                "confidence": getattr(data, "confidence", 1.0),
                "status": getattr(data, "status", MemoryStatus.ACTIVE),
                "access_count": getattr(data, "access_count", 0),
                "last_accessed_at": getattr(data, "last_accessed_at", None),
                "metadata": getattr(data, "metadata_json", {}) or {},
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            }
        return data

    @model_validator(mode="after")
    def populate_aliases(self) -> "MemoryResponse":
        if self.type is None:
            self.type = self.memory_type
        if self.importance is None:
            self.importance = self.importance_score
        return self


class MemoryListResponse(BaseModel):
    """Schema for returning a paginated list of memories."""

    items: list[MemoryResponse] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)


class LifecycleRuleResult(BaseModel):
    """Outcome report from executing memory lifecycle rules."""

    archived_count: int = 0
    decayed_count: int = 0
    reinforced_count: int = 0
    summary: str


class SemanticMemorySearchRequest(BaseModel):
    """Parameters for executing vector semantic memory search."""

    query: str = Field(..., min_length=1, description="Semantic text query to search for")
    top_k: int = Field(default=5, ge=1, le=100, description="Maximum number of memories to return")
    similarity_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity score required for matching (0.0 to 1.0)",
    )
    memory_type: MemoryType | None = Field(default=None, description="Optional memory type filter")
    metadata_filter: dict[str, Any] | None = Field(
        default=None, description="Key-value filters that must match metadata_json"
    )
    source: str | None = Field(default=None, description="Filter by provenance source")
    status: MemoryStatus | None = Field(
        default=MemoryStatus.ACTIVE, description="Filter by lifecycle status"
    )


class SemanticSearchResult(BaseModel):
    """Single match result from semantic vector memory retrieval."""

    memory: MemoryResponse
    similarity_score: float = Field(..., description="Cosine similarity score (0.0 to 1.0)")
    distance: float = Field(..., description="Cosine distance metric (0.0 to 2.0)")

    model_config = ConfigDict(from_attributes=True)


class SemanticSearchResponse(BaseModel):
    """Response payload containing ranked semantic memory search results."""

    query: str
    results: list[SemanticSearchResult] = Field(default_factory=list)
    count: int = 0
