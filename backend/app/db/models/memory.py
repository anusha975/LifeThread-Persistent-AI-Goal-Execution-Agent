import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
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


class MemoryType(StrEnum):
    """Categorical types of agent and user memories."""

    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    GOAL = "GOAL"
    PREFERENCE = "PREFERENCE"


class MemoryStatus(StrEnum):
    """Lifecycle statuses for a memory entry."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    SUPERSEDED = "SUPERSEDED"


class Memory(BaseDBModel):
    """Persistent memory record stored relationally for an authenticated user."""

    __tablename__ = "memories"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Owner user ID for strict multi-tenant isolation",
    )
    memory_type: Mapped[MemoryType] = mapped_column(
        SQLAlchemyEnum(MemoryType, native_enum=False, length=50),
        nullable=False,
        index=True,
        doc="Categorical memory classification (EPISODIC, SEMANTIC, GOAL, PREFERENCE)",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Raw textual memory content or observation",
    )
    importance_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        index=True,
        doc="Relevance or priority score between 0.0 and 1.0",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        index=True,
        doc="Confidence / certainty score between 0.0 and 1.0",
    )
    source: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="agent",
        index=True,
        doc="Originator or provenance of the memory (e.g. agent, user, observation, reflection)",
    )
    status: Mapped[MemoryStatus] = mapped_column(
        SQLAlchemyEnum(MemoryStatus, native_enum=False, length=50),
        nullable=False,
        default=MemoryStatus.ACTIVE,
        index=True,
        doc="Lifecycle state of the memory: ACTIVE, ARCHIVED, SUPERSEDED",
    )
    access_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of times this memory was retrieved or reinforced",
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when this memory was last retrieved or refreshed",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Arbitrary structured metadata and tags associated with this memory",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536),
        nullable=True,
        doc="1536-dimensional semantic vector embedding for similarity search",
    )

    # Relationship to user
    user: Mapped["User"] = relationship(
        "User",
        back_populates="memories",
    )

    @property
    def type(self) -> MemoryType:
        """Alias property matching requirement specification."""
        return self.memory_type

    @property
    def importance(self) -> float:
        """Alias property matching requirement specification."""
        return self.importance_score
