from datetime import timedelta

import pytest
from app.core.security import create_access_token
from app.core.token_store import TokenDenylist
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def clean_token_denylist() -> None:
    """Clear token revocation store before and after each test."""
    TokenDenylist.clear()
    yield
    TokenDenylist.clear()


@pytest.fixture
async def async_test_client():
    """Create a test client with an isolated in-memory SQLite database."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_application()

    async def override_get_db():
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_successful_registration(async_test_client: AsyncClient) -> None:
    """Verify new user registration succeeds with valid credentials."""
    payload = {
        "email": "agent.smith@lifethread.ai",
        "password": "SecurePassword123",
        "display_name": "Agent Smith",
        "timezone": "America/New_York",
    }
    response = await async_test_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "agent.smith@lifethread.ai"
    assert data["display_name"] == "Agent Smith"
    assert data["timezone"] == "America/New_York"
    assert data["is_active"] is True
    assert "id" in data
    # Password hash must NEVER be leaked in API response
    assert "password" not in data
    assert "password_hash" not in data


@pytest.mark.asyncio
async def test_duplicate_registration_prevented(async_test_client: AsyncClient) -> None:
    """Verify registering with an existing email returns HTTP 409 Conflict."""
    payload = {
        "email": "duplicate@lifethread.ai",
        "password": "Password123",
    }
    first_resp = await async_test_client.post("/api/v1/auth/register", json=payload)
    assert first_resp.status_code == 201

    # Second attempt with same email (case-insensitive)
    payload_dup = {
        "email": "DUPLICATE@lifethread.ai",
        "password": "AnotherPassword456",
    }
    second_resp = await async_test_client.post("/api/v1/auth/register", json=payload_dup)
    assert second_resp.status_code == 409
    data = second_resp.json()
    assert "error" in data
    assert "already exists" in data["error"]["message"].lower()


@pytest.mark.asyncio
async def test_successful_login(async_test_client: AsyncClient) -> None:
    """Verify login with correct credentials yields access and refresh tokens."""
    # Register user
    reg_payload = {"email": "login.test@lifethread.ai", "password": "Password123"}
    await async_test_client.post("/api/v1/auth/register", json=reg_payload)

    # Login
    login_payload = {"email": "login.test@lifethread.ai", "password": "Password123"}
    response = await async_test_client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_invalid_password(async_test_client: AsyncClient) -> None:
    """Verify login with incorrect password returns HTTP 401."""
    reg_payload = {"email": "badpwd.test@lifethread.ai", "password": "CorrectPassword1"}
    await async_test_client.post("/api/v1/auth/register", json=reg_payload)

    login_payload = {"email": "badpwd.test@lifethread.ai", "password": "WrongPassword9"}
    response = await async_test_client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 401
    data = response.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_protected_endpoint_without_token(async_test_client: AsyncClient) -> None:
    """Verify GET /api/v1/auth/me rejects requests lacking Authorization header."""
    response = await async_test_client.get("/api/v1/auth/me")
    assert response.status_code in [401, 403]


@pytest.mark.asyncio
async def test_protected_endpoint_with_valid_token(async_test_client: AsyncClient) -> None:
    """Verify GET /api/v1/auth/me returns profile when valid Bearer token is provided."""
    reg_payload = {
        "email": "me.test@lifethread.ai",
        "password": "Password123",
        "display_name": "Alice Developer",
    }
    await async_test_client.post("/api/v1/auth/register", json=reg_payload)

    login_resp = await async_test_client.post(
        "/api/v1/auth/login",
        json={"email": "me.test@lifethread.ai", "password": "Password123"},
    )
    token = login_resp.json()["access_token"]

    response = await async_test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "me.test@lifethread.ai"
    assert data["display_name"] == "Alice Developer"


@pytest.mark.asyncio
async def test_expired_or_invalid_token_rejected(async_test_client: AsyncClient) -> None:
    """Verify expired or tampered tokens are rejected with HTTP 401."""
    # Tampered token
    resp_tampered = await async_test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not.a.valid.jwt.token"},
    )
    assert resp_tampered.status_code == 401

    # Expired token
    expired_token, _, _ = create_access_token(
        subject="00000000-0000-0000-0000-000000000000",
        expires_delta=timedelta(seconds=-10),
    )
    resp_expired = await async_test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp_expired.status_code == 401
    assert "expired" in resp_expired.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_refresh_token_lifecycle(async_test_client: AsyncClient) -> None:
    """Verify refresh token endpoint issues new tokens and rotates old refresh token."""
    reg_payload = {"email": "refresh.test@lifethread.ai", "password": "Password123"}
    await async_test_client.post("/api/v1/auth/register", json=reg_payload)

    login_resp = await async_test_client.post(
        "/api/v1/auth/login",
        json={"email": "refresh.test@lifethread.ai", "password": "Password123"},
    )
    refresh_token = login_resp.json()["refresh_token"]

    # Refresh
    refresh_resp = await async_test_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_resp.status_code == 200
    new_data = refresh_resp.json()
    assert "access_token" in new_data
    assert "refresh_token" in new_data

    # Verify new access token works
    me_resp = await async_test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_data['access_token']}"},
    )
    assert me_resp.status_code == 200

    # Old refresh token should now be revoked (rotation)
    old_refresh_attempt = await async_test_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert old_refresh_attempt.status_code == 401


@pytest.mark.asyncio
async def test_logout_revocation(async_test_client: AsyncClient) -> None:
    """Verify logout revokes tokens and subsequent requests with revoked tokens fail."""
    reg_payload = {"email": "logout.test@lifethread.ai", "password": "Password123"}
    await async_test_client.post("/api/v1/auth/register", json=reg_payload)

    login_resp = await async_test_client.post(
        "/api/v1/auth/login",
        json={"email": "logout.test@lifethread.ai", "password": "Password123"},
    )
    access_token = login_resp.json()["access_token"]
    refresh_token = login_resp.json()["refresh_token"]

    # Logout revoking both tokens
    logout_resp = await async_test_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"refresh_token": refresh_token},
    )
    assert logout_resp.status_code == 200
    assert "logged out" in logout_resp.json()["message"].lower()

    # Attempting to use the access token should now be rejected
    protected_resp = await async_test_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert protected_resp.status_code == 401
    assert "revoked" in protected_resp.json()["error"]["message"].lower()

    # Attempting to refresh with revoked refresh token should also fail
    refresh_attempt = await async_test_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_attempt.status_code == 401
    assert "revoked" in refresh_attempt.json()["error"]["message"].lower()
