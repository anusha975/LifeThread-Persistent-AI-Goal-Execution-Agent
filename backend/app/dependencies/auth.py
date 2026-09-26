import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.core.token_store import TokenDenylist
from app.db.models.user import User
from app.db.session import get_db

security_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Dependency that extracts, decodes, and validates the bearer access token,

    retrieving the corresponding user from the database.
    """
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    from app.core.audit import SecurityAuditService, SecurityEventType

    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        SecurityAuditService.record_event(
            event_type=SecurityEventType.TOKEN_EXPIRED,
            action="AUTHENTICATE_TOKEN",
            details={"error": "Signature has expired"},
            severity="WARNING",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.InvalidTokenError:
        SecurityAuditService.record_event(
            event_type=SecurityEventType.TOKEN_MALFORMED,
            action="AUTHENTICATE_TOKEN",
            details={"error": "Invalid token or signature"},
            severity="WARNING",
        )
        raise credentials_exception from None

    # Validate token type
    if payload.get("type") != "access":
        SecurityAuditService.record_event(
            event_type=SecurityEventType.TOKEN_MALFORMED,
            action="AUTHENTICATE_TOKEN",
            details={"error": "Invalid token type, expected access"},
            severity="WARNING",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type: expected access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check revocation status
    jti = payload.get("jti")
    if jti and TokenDenylist.is_revoked(jti):
        SecurityAuditService.record_event(
            event_type=SecurityEventType.TOKEN_REVOKED_USED,
            action="AUTHENTICATE_TOKEN",
            details={"jti": jti},
            severity="CRITICAL",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        SecurityAuditService.record_event(
            event_type=SecurityEventType.TOKEN_MALFORMED,
            action="AUTHENTICATE_TOKEN",
            details={"error": "Missing subject"},
            severity="WARNING",
        )
        raise credentials_exception

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        SecurityAuditService.record_event(
            event_type=SecurityEventType.TOKEN_MALFORMED,
            action="AUTHENTICATE_TOKEN",
            details={"error": "Malformed user UUID"},
            severity="WARNING",
        )
        raise credentials_exception from None

    query = select(User).where(User.id == user_uuid)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if user is None:
        SecurityAuditService.record_event(
            event_type=SecurityEventType.UNAUTHORIZED_ACCESS_ATTEMPT,
            user_id=user_id_str,
            action="AUTHENTICATE_TOKEN",
            details={"error": "User does not exist"},
            severity="WARNING",
        )
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Dependency verifying that the authenticated user account is active."""
    if not current_user.is_active:
        from app.core.audit import SecurityAuditService, SecurityEventType

        SecurityAuditService.record_event(
            event_type=SecurityEventType.UNAUTHORIZED_ACCESS_ATTEMPT,
            user_id=str(current_user.id),
            action="ACCESS_INACTIVE_ACCOUNT",
            details={"error": "User account inactive"},
            severity="WARNING",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )
    return current_user


optional_security_scheme = HTTPBearer(auto_error=False)


async def get_optional_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(optional_security_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    """Dependency that extracts user if bearer token is present and valid, or returns None."""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            return None
        jti = payload.get("jti")
        if jti and TokenDenylist.is_revoked(jti):
            return None
        user_id_str = payload.get("sub")
        if not user_id_str:
            return None
        user_uuid = uuid.UUID(user_id_str)
        res = await db.execute(select(User).where(User.id == user_uuid))
        return res.scalar_one_or_none()
    except Exception:
        return None

