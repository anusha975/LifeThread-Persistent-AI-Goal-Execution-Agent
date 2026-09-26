"""Database access controls and multi-tenant user data isolation (Module 25).

Guarantees every database query is strictly scoped to the authenticated user.
Detects and logs IDOR (Insecure Direct Object Reference) attempts while returning
standard 404 responses to prevent user data enumeration.
"""

import logging
import uuid
from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import SecurityAuditService, SecurityEventType

logger = logging.getLogger("lifethread.security.access_control")

T = TypeVar("T")


class DatabaseAccessControl:
    """Enforces strict row-level tenant isolation and prevents IDOR attacks."""

    @classmethod
    async def get_user_resource_or_404(
        cls,
        db: AsyncSession,
        model: type[T],
        resource_id: uuid.UUID,
        user_id: uuid.UUID,
        resource_name: str = "resource",
    ) -> T:
        """Fetch a database record ensuring it is strictly owned by user_id.

        If the record exists under a different user, an IDOR security audit event
        is logged at CRITICAL severity, and an HTTP 404 is raised.

        Raises:
            HTTPException: 404 if record does not exist or belongs to another user.
        """
        # 1. Query with strict user scoping
        stmt = select(model).where(
            model.id == resource_id,  # type: ignore[attr-defined]
            model.user_id == user_id,  # type: ignore[attr-defined]
        )
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()

        if record is not None:
            return record

        # 2. Check if the resource actually exists under a different user (IDOR attempt detection)
        idor_stmt = select(model.user_id).where(model.id == resource_id)  # type: ignore[attr-defined]
        idor_res = await db.execute(idor_stmt)
        actual_owner_id = idor_res.scalar_one_or_none()

        if actual_owner_id is not None and actual_owner_id != user_id:
            SecurityAuditService.record_event(
                event_type=SecurityEventType.IDOR_ATTEMPT_DETECTED,
                user_id=str(user_id),
                resource_type=resource_name,
                resource_id=str(resource_id),
                action=f"ACCESS_{resource_name.upper()}",
                details={
                    "actual_owner_id": str(actual_owner_id),
                    "attempted_by": str(user_id),
                    "violation": "Attempted to access another tenant's resource",
                },
                severity="CRITICAL",
            )
            logger.warning(
                "SECURITY [IDOR_DETECTED] User %s attempted to access %s %s owned by %s",
                user_id,
                resource_name,
                resource_id,
                actual_owner_id,
            )

        # 3. Always return 404 Not Found to prevent data existence leakage
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource_name.capitalize()} not found",
        )
