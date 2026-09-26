from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import BaseDBModel

if TYPE_CHECKING:
    from app.db.models.document import Document
    from app.db.models.goal import Goal
    from app.db.models.memory import Memory


class User(BaseDBModel):
    """User account entity representing a registered platform user."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        doc="Unique email address used for login and notifications",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Securely hashed password (bcrypt)",
    )
    display_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Optional user-chosen display name",
    )
    timezone: Mapped[str] = mapped_column(
        String(50),
        default="UTC",
        nullable=False,
        doc="User preferred timezone identifier",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether this user account is active",
    )

    # Relationships
    goals: Mapped[list["Goal"]] = relationship(
        "Goal",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    memories: Mapped[list["Memory"]] = relationship(
        "Memory",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="user",
        cascade="all, delete-orphan",
    )
