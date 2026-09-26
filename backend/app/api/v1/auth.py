import logging
import uuid
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.token_store import TokenDenylist
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    LogoutResponse,
    RefreshTokenRequest,
    TokenResponse,
)
from app.schemas.user import UserCreate, UserResponse

logger = logging.getLogger("lifethread.auth")
router = APIRouter(prefix="/auth", tags=["Authentication & Users"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register New User",
    description="Register a new platform user account with email and secure password.",
)
async def register(
    user_in: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Create a new user ensuring unique email address and hashed password."""
    # Check for duplicate email (case-insensitive)
    query = select(User).where(func.lower(User.email) == user_in.email.lower())
    result = await db.execute(query)
    existing_user = result.scalar_one_or_none()

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists",
        )

    # Hash password securely
    hashed_pwd = hash_password(user_in.password)

    new_user = User(
        email=user_in.email.lower(),
        password_hash=hashed_pwd,
        display_name=user_in.display_name,
        timezone=user_in.timezone,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()
    await db.refresh(new_user)

    logger.info("Registered new user account", extra={"user_id": str(new_user.id)})
    return UserResponse.model_validate(new_user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="User Login",
    description="Authenticate user with email and password, returning JWT access and refresh tokens.",
)
async def login(
    login_data: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Validate credentials and issue new JWT access and refresh tokens."""
    query = select(User).where(func.lower(User.email) == login_data.email.lower())
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    from app.core.audit import SecurityAuditService, SecurityEventType

    if user is None or not verify_password(login_data.password, user.password_hash):
        SecurityAuditService.record_event(
            event_type=SecurityEventType.LOGIN_FAILED,
            action="LOGIN",
            details={"email": login_data.email},
            severity="WARNING",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        SecurityAuditService.record_event(
            event_type=SecurityEventType.UNAUTHORIZED_ACCESS_ATTEMPT,
            user_id=str(user.id),
            action="LOGIN_INACTIVE",
            details={"email": user.email},
            severity="WARNING",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    SecurityAuditService.record_event(
        event_type=SecurityEventType.LOGIN_SUCCESS,
        user_id=str(user.id),
        action="LOGIN",
        details={"email": user.email},
        severity="INFO",
    )

    access_token, _, expires_in = create_access_token(subject=str(user.id))
    refresh_token, _, _ = create_refresh_token(subject=str(user.id))

    logger.info("User successfully logged in", extra={"user_id": str(user.id)})
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh Access Token",
    description="Issue a new JWT access token using a valid, unrevoked refresh token.",
)
async def refresh_token_endpoint(
    refresh_data: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Verify refresh token, perform rotation by revoking old refresh token, and issue new tokens."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(refresh_data.refresh_token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise credentials_exception from None

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type: expected refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jti = payload.get("jti")
    if jti and TokenDenylist.is_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise credentials_exception

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise credentials_exception from None

    query = select(User).where(User.id == user_uuid)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise credentials_exception

    # Revoke old refresh token (token rotation)
    if jti:
        exp = float(payload.get("exp", 0))
        TokenDenylist.revoke(jti, exp)

    # Issue fresh tokens
    new_access_token, _, expires_in = create_access_token(subject=str(user.id))
    new_refresh_token, _, _ = create_refresh_token(subject=str(user.id))

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=expires_in,
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
    summary="User Logout",
    description="Revoke the provided access and/or refresh tokens.",
)
async def logout(
    request: Request,
    logout_data: LogoutRequest | None = None,
) -> LogoutResponse:
    """Revoke tokens to prevent reuse."""
    # Revoke access token from Authorization header if present
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        raw_token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = decode_token(raw_token)
            jti = payload.get("jti")
            if jti:
                exp = float(payload.get("exp", 0))
                TokenDenylist.revoke(jti, exp)
        except Exception:
            pass

    # Revoke refresh token if supplied in body
    if logout_data and logout_data.refresh_token:
        try:
            payload = decode_token(logout_data.refresh_token)
            jti = payload.get("jti")
            if jti:
                exp = float(payload.get("exp", 0))
                TokenDenylist.revoke(jti, exp)
        except Exception:
            pass

    return LogoutResponse(message="Successfully logged out")


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Current User Profile",
    description="Retrieve profile details for the authenticated user.",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserResponse:
    """Return profile for authenticated user."""
    return UserResponse.model_validate(current_user)
