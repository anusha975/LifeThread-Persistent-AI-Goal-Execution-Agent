import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from app.core.exceptions import LifeThreadException
from app.db.models.memory import Memory, MemoryType
from app.schemas.memory import MemoryCreate, MemoryUpdate
from app.services.memory import MemoryService
from fastapi import HTTPException
from lifethread_agent.tools import ToolPermissionLevel, ToolRegistry
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("lifethread.mcp.tools.memory")


# ============================================================================
# STRUCTURED SCHEMAS FOR MEMORY MCP TOOLS
# ============================================================================


class MemoryToolOutput(BaseModel):
    """Structured representation of a stored memory entity."""

    id: uuid.UUID
    user_id: uuid.UUID
    memory_type: MemoryType
    content: str
    importance_score: float
    importance: float | None = None
    confidence: float = 1.0
    source: str
    status: str = "ACTIVE"
    access_count: int = 0
    last_accessed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_db_model(cls, memory: Memory) -> "MemoryToolOutput":
        return cls(
            id=memory.id,
            user_id=memory.user_id,
            memory_type=memory.memory_type,
            content=memory.content,
            importance_score=memory.importance_score,
            importance=memory.importance_score,
            confidence=getattr(memory, "confidence", 1.0),
            source=memory.source,
            status=getattr(memory.status, "value", str(memory.status)),
            access_count=getattr(memory, "access_count", 0),
            last_accessed_at=getattr(memory, "last_accessed_at", None),
            metadata=memory.metadata_json or {},
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )


class MemorySearchResultToolOutput(BaseModel):
    """Structured output for relational memory search results."""

    items: list[MemoryToolOutput] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)


class DeleteMemoryToolOutput(BaseModel):
    """Structured output confirming memory deletion."""

    success: bool
    memory_id: uuid.UUID
    message: str


class StoreMemoryToolInput(BaseModel):
    """Input payload to store a new memory record relationally."""

    user_id: uuid.UUID = Field(
        ..., description="Unique UUID of the user owner for strict multi-tenant isolation"
    )
    content: str = Field(..., min_length=1, description="Memory text content or observation")
    memory_type: MemoryType = Field(
        default=MemoryType.EPISODIC,
        description="Memory type category (EPISODIC, SEMANTIC, GOAL, PREFERENCE)",
    )
    importance_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Relevance or priority score between 0.0 (lowest) and 1.0 (critical)",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence / certainty score between 0.0 and 1.0",
    )
    source: str = Field(
        default="agent",
        min_length=1,
        max_length=255,
        description="Provenance of the memory (e.g. agent, user, observation, tool)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured arbitrary metadata dictionary",
    )

    @field_validator("content")
    @classmethod
    def validate_content_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Memory content cannot be empty or whitespace only")
        return stripped


class RetrieveMemoryToolInput(BaseModel):
    """Input payload to retrieve a memory record by ID."""

    memory_id: uuid.UUID = Field(..., description="Unique UUID of the target memory")
    user_id: uuid.UUID = Field(
        ..., description="UUID of the authenticated user requesting the memory"
    )


class SearchMemoryToolInput(BaseModel):
    """Input payload to search memories using relational filters."""

    user_id: uuid.UUID = Field(
        ..., description="UUID of the authenticated user performing the search"
    )
    query: str | None = Field(
        default=None, description="Optional text query to filter memory content (case-insensitive)"
    )
    memory_type: MemoryType | None = Field(
        default=None,
        description="Optional filter by memory type (EPISODIC, SEMANTIC, GOAL, PREFERENCE)",
    )
    min_importance: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional minimum importance score threshold",
    )
    min_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional minimum confidence score threshold",
    )
    source: str | None = Field(default=None, description="Optional filter by source/originator")
    limit: int = Field(default=50, ge=1, le=100, description="Max memories to return")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")


class UpdateMemoryToolInput(BaseModel):
    """Input payload to update an existing memory record."""

    memory_id: uuid.UUID = Field(..., description="Unique UUID of the memory to update")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated memory owner")
    content: str | None = Field(default=None, min_length=1, description="Updated memory text")
    memory_type: MemoryType | None = Field(default=None, description="Updated memory type")
    importance_score: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Updated importance score"
    )
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Updated confidence score"
    )
    source: str | None = Field(
        default=None, min_length=1, max_length=255, description="Updated source"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Updated metadata dictionary (replaces existing metadata)"
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


class DeleteMemoryToolInput(BaseModel):
    """Input payload to delete an existing memory record."""

    memory_id: uuid.UUID = Field(..., description="Unique UUID of the memory to delete")
    user_id: uuid.UUID = Field(..., description="UUID of the authenticated memory owner")


# ============================================================================
# HELPER: RESOLVE DB SESSION
# ============================================================================


@asynccontextmanager
async def _resolve_db_session(context: dict[str, Any] | None) -> AsyncGenerator[AsyncSession, None]:
    """Provide an AsyncSession from execution context or a fresh transaction context."""
    if context and "db" in context:
        yield context["db"]
    else:
        from app.db.session import transaction_context

        async with transaction_context() as session:
            yield session


# ============================================================================
# TOOL REGISTRATION
# ============================================================================


def register_memory_mcp_tools(registry: ToolRegistry) -> None:
    """Register all 5 Memory MCP tools into the given registry."""

    # 1. STORE MEMORY
    @registry.tool(
        name="store_memory",
        description="Store a new memory (episodic, semantic, goal, or preference) relationally with user isolation and importance score.",
        input_schema=StoreMemoryToolInput,
        output_schema=MemoryToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def store_memory(
        user_id: uuid.UUID,
        content: str,
        memory_type: MemoryType = MemoryType.EPISODIC,
        importance_score: float = 0.5,
        confidence: float = 1.0,
        source: str = "agent",
        metadata: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "MCP Tool [store_memory] invoked by user [%s] type [%s] importance [%s] confidence [%s]",
            user_id,
            memory_type.value,
            importance_score,
            confidence,
        )
        create_data = MemoryCreate(
            content=content,
            memory_type=memory_type,
            importance_score=importance_score,
            confidence=confidence,
            source=source,
            metadata=metadata or {},
        )
        async with _resolve_db_session(context) as session:
            try:
                memory = await MemoryService.store_memory(
                    db=session,
                    user_id=user_id,
                    create_data=create_data,
                )
                output = MemoryToolOutput.from_db_model(memory)
                return output.model_dump(mode="json")
            except HTTPException as exc:
                logger.warning("MCP [store_memory] HTTPException: %s", exc.detail)
                raise LifeThreadException(
                    message=str(exc.detail),
                    code="NOT_FOUND" if exc.status_code == 404 else "MEMORY_ERROR",
                    status_code=exc.status_code,
                ) from exc

    # 2. RETRIEVE MEMORY
    @registry.tool(
        name="retrieve_memory",
        description="Retrieve an existing memory record by memory_id ensuring strict user isolation.",
        input_schema=RetrieveMemoryToolInput,
        output_schema=MemoryToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def retrieve_memory(
        memory_id: uuid.UUID,
        user_id: uuid.UUID,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "MCP Tool [retrieve_memory] invoked for memory [%s] by user [%s]",
            memory_id,
            user_id,
        )
        async with _resolve_db_session(context) as session:
            try:
                memory = await MemoryService.get_memory_by_id(
                    db=session,
                    memory_id=memory_id,
                    user_id=user_id,
                )
                output = MemoryToolOutput.from_db_model(memory)
                return output.model_dump(mode="json")
            except HTTPException as exc:
                logger.warning("MCP [retrieve_memory] HTTPException: %s", exc.detail)
                raise LifeThreadException(
                    message=str(exc.detail),
                    code="NOT_FOUND" if exc.status_code == 404 else "MEMORY_ERROR",
                    status_code=exc.status_code,
                ) from exc

    # 3. SEARCH MEMORY
    @registry.tool(
        name="search_memory",
        description="Search memories relationally by query substring, memory type, importance, and source with user isolation.",
        input_schema=SearchMemoryToolInput,
        output_schema=MemorySearchResultToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def search_memory(
        user_id: uuid.UUID,
        query: str | None = None,
        memory_type: MemoryType | None = None,
        min_importance: float | None = None,
        min_confidence: float | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "MCP Tool [search_memory] invoked by user [%s] query [%s] type [%s] min_imp [%s]",
            user_id,
            query,
            memory_type.value if memory_type else None,
            min_importance,
        )
        async with _resolve_db_session(context) as session:
            try:
                memories, total = await MemoryService.search_memories(
                    db=session,
                    user_id=user_id,
                    query=query,
                    memory_type=memory_type,
                    min_importance=min_importance,
                    min_confidence=min_confidence,
                    source=source,
                    limit=limit,
                    offset=offset,
                )
                items = [MemoryToolOutput.from_db_model(m) for m in memories]
                output = MemorySearchResultToolOutput(items=items, total=total)
                return output.model_dump(mode="json")
            except HTTPException as exc:
                logger.warning("MCP [search_memory] HTTPException: %s", exc.detail)
                raise LifeThreadException(
                    message=str(exc.detail),
                    code="NOT_FOUND" if exc.status_code == 404 else "MEMORY_ERROR",
                    status_code=exc.status_code,
                ) from exc

    # 4. UPDATE MEMORY
    @registry.tool(
        name="update_memory",
        description="Update an existing memory record's content, type, importance score, source, or metadata.",
        input_schema=UpdateMemoryToolInput,
        output_schema=MemoryToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def update_memory(
        memory_id: uuid.UUID,
        user_id: uuid.UUID,
        content: str | None = None,
        memory_type: MemoryType | None = None,
        importance_score: float | None = None,
        confidence: float | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "MCP Tool [update_memory] invoked for memory [%s] by user [%s]",
            memory_id,
            user_id,
        )
        update_data = MemoryUpdate(
            content=content,
            memory_type=memory_type,
            importance_score=importance_score,
            confidence=confidence,
            source=source,
            metadata=metadata,
        )
        async with _resolve_db_session(context) as session:
            try:
                updated = await MemoryService.update_memory(
                    db=session,
                    memory_id=memory_id,
                    user_id=user_id,
                    update_data=update_data,
                )
                output = MemoryToolOutput.from_db_model(updated)
                return output.model_dump(mode="json")
            except HTTPException as exc:
                logger.warning("MCP [update_memory] HTTPException: %s", exc.detail)
                raise LifeThreadException(
                    message=str(exc.detail),
                    code="NOT_FOUND" if exc.status_code == 404 else "MEMORY_ERROR",
                    status_code=exc.status_code,
                ) from exc

    # 5. DELETE MEMORY
    @registry.tool(
        name="delete_memory",
        description="Permanently delete a memory record belonging to the authenticated user.",
        input_schema=DeleteMemoryToolInput,
        output_schema=DeleteMemoryToolOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def delete_memory(
        memory_id: uuid.UUID,
        user_id: uuid.UUID,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "MCP Tool [delete_memory] invoked for memory [%s] by user [%s]",
            memory_id,
            user_id,
        )
        async with _resolve_db_session(context) as session:
            try:
                await MemoryService.delete_memory(
                    db=session,
                    memory_id=memory_id,
                    user_id=user_id,
                )
                output = DeleteMemoryToolOutput(
                    success=True,
                    memory_id=memory_id,
                    message="Memory record deleted successfully.",
                )
                return output.model_dump(mode="json")
            except HTTPException as exc:
                logger.warning("MCP [delete_memory] HTTPException: %s", exc.detail)
                raise LifeThreadException(
                    message=str(exc.detail),
                    code="NOT_FOUND" if exc.status_code == 404 else "MEMORY_ERROR",
                    status_code=exc.status_code,
                ) from exc
