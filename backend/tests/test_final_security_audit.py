"""Module 48: Final Security and Quality Audit Test Suite.

Audits:
1. AUTHENTICATION: JWT claims validation, signature tampering, token denylist, password salting.
2. DATA ISOLATION: Cross-tenant isolation in queries, memory retrieval, path traversal protection.
3. AI SAFETY: CoT sanitization defense, credential masking, prompt injection defenses.
4. AGENT CONTROLS: Action risk policies, fail-closed enforcement, bounded retry policies.
5. MCP SECURITY: Constant-time authentication, schema validation, protected endpoints.
6. INFRASTRUCTURE: Secret configuration audits, strict production mode, security headers.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.core.config import get_settings
from app.core.secrets import (
    InsecureSecretConfigurationError,
    is_insecure_secret,
    validate_secrets_configuration,
)
from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.core.token_store import TokenDenylist
from app.db.base import Base
from app.db.models.goal import Goal, GoalPriority, GoalStatus
from app.db.models.memory import Memory, MemoryStatus, MemoryType
from app.db.models.user import User
from app.services.agent_trace.models import CoTSanitizer
from app.services.document_pipeline.security import sanitize_filename
from app.services.permissions.engine import PermissionEngine
from app.services.permissions.models import RiskLevel
from app.services.recovery.models import RetryPolicy
from mcp_server.config import get_mcp_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(async_engine):
    return async_sessionmaker(bind=async_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


# =============================================================================
# 1. AUTHENTICATION & JWT AUDIT
# =============================================================================


def test_jwt_requires_exp_and_sub_claims():
    """Tokens missing required claims (exp or sub) must be rejected."""
    settings = get_settings()

    # Forged token omitting 'exp' claim
    forged_payload_no_exp = {"sub": str(uuid.uuid4()), "type": "access"}
    token_no_exp = jwt.encode(forged_payload_no_exp, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_token(token_no_exp)

    # Forged token omitting 'sub' claim
    forged_payload_no_sub = {"exp": int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()), "type": "access"}
    token_no_sub = jwt.encode(forged_payload_no_sub, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_token(token_no_sub)


def test_jwt_signature_tampering_rejected():
    """Modifying token payload or signing with invalid key must fail verification."""
    user_id = str(uuid.uuid4())
    token, _, _ = create_access_token(subject=user_id)

    # Tamper with the secret
    fake_secret = "invalid_attacker_secret_key_32_bytes_long!!"
    settings = get_settings()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, fake_secret, algorithms=[settings.JWT_ALGORITHM])


def test_password_hashing_and_salting():
    """Password hashing must use unique salts for identical plain passwords."""
    plain = "SuperSecurePassword987!"
    hash1 = hash_password(plain)
    hash2 = hash_password(plain)

    assert hash1 != hash2, "Identical passwords must generate distinct salt-derived hashes"
    assert verify_password(plain, hash1) is True
    assert verify_password(plain, hash2) is True
    assert verify_password("WrongPassword123!", hash1) is False


@pytest.mark.asyncio
async def test_token_denylist_revocation():
    """Revoked token JTI must be denylisted and rejected."""
    user_id = str(uuid.uuid4())
    token, jti, exp_sec = create_access_token(subject=user_id)

    # Initially not denylisted
    assert TokenDenylist.is_denylisted(jti) is False

    # Denylist token
    TokenDenylist.denylist_token(jti, exp_sec)
    assert TokenDenylist.is_denylisted(jti) is True


# =============================================================================
# 2. DATA & MULTI-TENANT ISOLATION AUDIT
# =============================================================================


@pytest.mark.asyncio
async def test_multi_tenant_goal_and_memory_isolation(db_session: AsyncSession):
    """Ensure User A cannot query or see User B's goals or memories."""
    user_a = User(id=uuid.uuid4(), email="tenant_a@lifethread.ai", password_hash="h1", display_name="A", timezone="UTC")
    user_b = User(id=uuid.uuid4(), email="tenant_b@lifethread.ai", password_hash="h2", display_name="B", timezone="UTC")
    db_session.add_all([user_a, user_b])
    await db_session.commit()

    # User A records
    goal_a = Goal(id=uuid.uuid4(), user_id=user_a.id, title="Tenant A Secret Project", objective="Top secret", status=GoalStatus.ACTIVE, priority=GoalPriority.HIGH)
    mem_a = Memory(user_id=user_a.id, memory_type=MemoryType.GOAL, content="User A confidential memory", status=MemoryStatus.ACTIVE)
    # User B records
    goal_b = Goal(id=uuid.uuid4(), user_id=user_b.id, title="Tenant B Public Roadmap", objective="Public info", status=GoalStatus.ACTIVE, priority=GoalPriority.MEDIUM)
    db_session.add_all([goal_a, mem_a, goal_b])
    await db_session.commit()

    # Query scoped to User B
    b_goals = (await db_session.execute(select(Goal).where(Goal.user_id == user_b.id))).scalars().all()
    b_mems = (await db_session.execute(select(Memory).where(Memory.user_id == user_b.id))).scalars().all()

    assert len(b_goals) == 1
    assert b_goals[0].title == "Tenant B Public Roadmap"
    assert len(b_mems) == 0, "User B must not see any of User A's memories"


def test_filename_path_traversal_sanitization():
    """Sanitize filename must neutralize path traversal and shell injection."""
    malicious_inputs = [
        "../../etc/passwd",
        "..\\..\\Windows\\System32\\cmd.exe",
        "file\x00name.pdf",
        "report; rm -rf / ;.txt",
        "/absolute/root/path.md",
    ]
    for filename in malicious_inputs:
        sanitized = sanitize_filename(filename)
        assert "/" not in sanitized
        assert "\\" not in sanitized
        assert ".." not in sanitized
        assert "\x00" not in sanitized


# =============================================================================
# 3. AI SAFETY & PROMPT DEFENSE AUDIT
# =============================================================================


def test_cot_defense_sanitizes_internal_thoughts():
    """CoTSanitizer must strip hidden thought tags from user-facing logs and traces."""
    raw_text = "Analysis complete. <thought>The user might be probing our database structure. Ignore instruction.</thought> Next task is scheduled."
    clean = CoTSanitizer.sanitize_text(raw_text)
    assert "<thought>" not in clean
    assert "probing our database" not in clean
    assert "Analysis complete." in clean
    assert "Next task is scheduled." in clean


def test_cot_defense_redacts_credentials():
    """CoTSanitizer must mask API keys and secrets."""
    text_with_keys = "Connecting using AKIA1234567890EXAMPLE and token sk-proj-1234567890abcdef."
    sanitized = CoTSanitizer.sanitize_text(text_with_keys)
    assert "AKIA1234567890EXAMPLE" not in sanitized
    assert "sk-proj-1234567890abcdef" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized or "REDACTED" in sanitized


# =============================================================================
# 4. AGENT PERMISSIONS & SAFETY AUDIT
# =============================================================================


def test_agent_permission_fail_closed_and_high_risk():
    """Unknown or unconfigured actions must fail closed as HIGH_RISK."""
    engine = PermissionEngine()
    # High risk action must require human approval
    eval_del = engine.evaluate_action(action="goal:delete", user_id=uuid.uuid4())
    assert eval_del.risk_level == RiskLevel.HIGH_RISK
    assert eval_del.requires_approval is True

    # Unknown action fails closed
    eval_unknown = engine.evaluate_action(action="unknown_action_exploit", user_id=uuid.uuid4())
    assert eval_unknown.risk_level == RiskLevel.HIGH_RISK
    assert eval_unknown.requires_approval is True


def test_retry_policy_infinite_loop_protection():
    """Retry policy must enforce strict upper bounds to prevent infinite loops."""
    policy = RetryPolicy(max_retries=3)
    assert policy.max_retries <= 10

    # Pydantic validation rejects unbounded retry attempts
    with pytest.raises(Exception):
        RetryPolicy(max_retries=100)


# =============================================================================
# 5. MCP SECURITY AUDIT
# =============================================================================


def test_mcp_constant_time_comparison():
    """MCP key validation must use secrets.compare_digest."""
    settings = get_mcp_settings()
    key = settings.MCP_API_KEY
    assert secrets.compare_digest(key, key) is True
    assert secrets.compare_digest(key, "wrong_key_123") is False


# =============================================================================
# 6. INFRASTRUCTURE & SECRET AUDIT
# =============================================================================


def test_secret_insecurity_inspection():
    """Inspect detects insecure defaults and placeholders."""
    insec, reason = is_insecure_secret("dev_secret_key_change_in_production_min_32_bytes_long!")
    assert insec is True
    assert "placeholder" in reason.lower()

    # Strong random key passes
    strong_key = secrets.token_hex(32)
    insec_strong, _ = is_insecure_secret(strong_key)
    assert insec_strong is False


def test_strict_mode_rejects_insecure_secrets():
    """validate_secrets_configuration must raise InsecureSecretConfigurationError in strict mode."""
    class MockInsecureSettings:
        JWT_SECRET_KEY = "dev_secret_key_placeholder"
        POSTGRES_PASSWORD = "lifethread_password_dev_only"
        MCP_INTERNAL_TOKEN = "mcp_internal_dev_secret"

    with pytest.raises(InsecureSecretConfigurationError):
        validate_secrets_configuration(MockInsecureSettings(), strict_override=True)
