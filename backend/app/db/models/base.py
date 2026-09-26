import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, event, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy ORM models."""

    pass


class UUIDPrimaryKeyMixin:
    """Mixin providing a UUID v4 primary key with indexing."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        doc="Unique UUID v4 primary key identifier",
    )


class TimestampMixin:
    """Mixin providing automatic timezone-aware created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        doc="Timestamp when the entity was created in UTC",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
        doc="Timestamp when the entity was last updated in UTC",
    )


class BaseDBModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Abstract base model combining UUID primary key and timestamp tracking.

    All future domain models (e.g. Goal, Task, Memory) inherit from this base.
    """

    __abstract__ = True


@event.listens_for(BaseDBModel, "init", propagate=True)
def _init_uuid_primary_key(target: Any, args: Any, kwargs: dict[str, Any]) -> None:
    """Ensure instantiated models have a generated UUID primary key immediately."""
    if "id" not in kwargs or kwargs["id"] is None:
        kwargs["id"] = uuid.uuid4()
