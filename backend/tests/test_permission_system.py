"""Comprehensive test suite for Module 24: Human-in-the-Loop Permission System.

Verifies:
1. Risk levels: LOW_RISK, MEDIUM_RISK, HIGH_RISK
2. Core types: ActionPolicy, PermissionRequest, Approval, Rejection
3. Execution behaviors:
   - LOW_RISK: May execute automatically
   - MEDIUM_RISK: May require configurable confirmation
   - HIGH_RISK: Always requires explicit user approval
4. Every approval records: user, action, reason, timestamp, decision
5. Fail-closed behavior when permission information is missing
6. ACCEPTANCE CRITERIA: The agent cannot execute an action requiring approval
   without an explicit approval record.
"""

import uuid
from datetime import UTC, datetime

import pytest
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models.permission import (
    ActionPolicyModel,
    ApprovalModel,
    PermissionRequestModel,
    RejectionModel,
)
from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.main import app
from app.services.permissions import (
    ActionPolicy,
    Approval,
    DecisionType,
    InvalidApprovalError,
    MissingPermissionInfoError,
    PermissionDeniedError,
    PermissionEngine,
    PermissionRequest,
    PermissionRequiredError,
    PolicyRegistry,
    Rejection,
    RequestStatus,
    RiskLevel,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"perm_user_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="hashed_pw_test",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_token(test_user: User) -> str:
    token, _, _ = create_access_token(subject=str(test_user.id))
    return token


@pytest.fixture
def clean_engine() -> PermissionEngine:
    """Provide a fresh permission engine with clean state and default policies."""
    registry = PolicyRegistry()
    return PermissionEngine(policy_registry=registry)


# =============================================================================
# UNIT TESTS: MODELS & DEFINITIONS
# =============================================================================


def test_risk_level_definitions():
    """Verify LOW_RISK, MEDIUM_RISK, and HIGH_RISK are properly defined."""
    assert RiskLevel.LOW_RISK == "LOW_RISK"
    assert RiskLevel.MEDIUM_RISK == "MEDIUM_RISK"
    assert RiskLevel.HIGH_RISK == "HIGH_RISK"
    assert len(RiskLevel) == 3


def test_core_entities_creation():
    """Verify ActionPolicy, PermissionRequest, Approval, and Rejection instantiation."""
    policy = ActionPolicy(
        action_pattern="goal:archive",
        risk_level=RiskLevel.MEDIUM_RISK,
        description="Archiving a goal roadmap",
        require_confirmation_for_medium=True,
    )
    assert policy.action_pattern == "goal:archive"
    assert policy.risk_level == RiskLevel.MEDIUM_RISK

    req = PermissionRequest(
        user_id="user_123",
        action="goal:archive",
        parameters={"goal_id": "g-1"},
        risk_level=RiskLevel.MEDIUM_RISK,
        reason="Goal has met target milestones",
    )
    assert req.status == RequestStatus.PENDING
    assert req.action == "goal:archive"

    appr = Approval(
        user="user_123",
        action="goal:archive",
        reason="Approved by user",
        timestamp=datetime.now(UTC),
        decision="APPROVED",
    )
    assert appr.user == "user_123"
    assert appr.decision == "APPROVED"

    rej = Rejection(
        user="user_123",
        action="goal:archive",
        reason="Still need more time",
        timestamp=datetime.now(UTC),
        decision="REJECTED",
    )
    assert rej.user == "user_123"
    assert rej.decision == "REJECTED"


def test_approval_records_all_required_fields():
    """Requirement: Every approval must record: user, action, reason, timestamp, decision."""
    now = datetime.now(UTC)
    approval = Approval(
        user="alice@example.com",
        action="deploy:production",
        reason="Verified staging release passes all checks",
        timestamp=now,
        decision="APPROVED",
    )

    # Assert all 5 mandatory fields are present and non-empty
    assert approval.user == "alice@example.com"
    assert approval.action == "deploy:production"
    assert approval.reason == "Verified staging release passes all checks"
    assert approval.timestamp == now
    assert approval.decision == "APPROVED"


def test_rejection_records_all_required_fields():
    """Requirement: Every rejection must record: user, action, reason, timestamp, decision."""
    now = datetime.now(UTC)
    rejection = Rejection(
        user="bob@example.com",
        action="payment:charge",
        reason="Price mismatch on line item",
        timestamp=now,
        decision="REJECTED",
    )

    assert rejection.user == "bob@example.com"
    assert rejection.action == "payment:charge"
    assert rejection.reason == "Price mismatch on line item"
    assert rejection.timestamp == now
    assert rejection.decision == "REJECTED"


# =============================================================================
# RISK LEVEL BEHAVIORS: LOW, MEDIUM, HIGH
# =============================================================================


@pytest.mark.asyncio
async def test_low_risk_may_execute_automatically(clean_engine: PermissionEngine):
    """Rule: LOW_RISK may execute automatically."""
    action = "query:status"
    user = "alice"

    eval_res = clean_engine.evaluate_action(user=user, action=action)
    assert eval_res.risk_level == RiskLevel.LOW_RISK
    assert eval_res.requires_approval is False
    assert eval_res.can_execute_immediately is True

    executed = False

    def sample_low_risk_action():
        nonlocal executed
        executed = True
        return {"status": "HEALTHY"}

    # Execute without passing explicit approval
    result, approval_record = await clean_engine.execute_with_permission(
        user=user,
        action=action,
        func=sample_low_risk_action,
    )

    assert executed is True
    assert result == {"status": "HEALTHY"}
    # Even auto-approved actions must record the 5 required fields
    assert approval_record.user == user
    assert approval_record.action == action
    assert "Auto-approved" in approval_record.reason
    assert approval_record.timestamp is not None
    assert approval_record.decision == DecisionType.AUTO_APPROVED.value


@pytest.mark.asyncio
async def test_medium_risk_configurable_confirmation(clean_engine: PermissionEngine):
    """Rule: MEDIUM_RISK may require configurable confirmation."""
    action = "goal:update_title"
    user = "charlie"

    # Case 1: Default configuration -> confirmation required
    eval_default = clean_engine.evaluate_action(user=user, action=action)
    assert eval_default.risk_level == RiskLevel.MEDIUM_RISK
    assert eval_default.requires_approval is True
    assert eval_default.can_execute_immediately is False

    # Attempting to execute without approval raises PermissionRequiredError
    with pytest.raises(PermissionRequiredError) as exc_info:
        await clean_engine.execute_with_permission(
            user=user,
            action=action,
            func=lambda: "updated",
        )
    assert exc_info.value.action == action
    assert exc_info.value.risk_level == RiskLevel.MEDIUM_RISK.value

    # Case 2: User configures confirmation to False -> executes automatically
    clean_engine.set_user_medium_confirmation(user=user, require_confirmation=False)
    eval_configured = clean_engine.evaluate_action(user=user, action=action)
    assert eval_configured.risk_level == RiskLevel.MEDIUM_RISK
    assert eval_configured.requires_approval is False
    assert eval_configured.can_execute_immediately is True

    result, auto_approval = await clean_engine.execute_with_permission(
        user=user,
        action=action,
        func=lambda: "updated_automatically",
    )
    assert result == "updated_automatically"
    assert auto_approval.decision == DecisionType.AUTO_APPROVED.value

    # Case 3: Explicit per-call override
    eval_override = clean_engine.evaluate_action(
        user=user,
        action=action,
        confirmation_override=True,
    )
    assert eval_override.requires_approval is True


@pytest.mark.asyncio
async def test_high_risk_always_requires_explicit_user_approval(clean_engine: PermissionEngine):
    """Rule: HIGH_RISK always requires explicit user approval."""
    action = "goal:delete"
    user = "david"

    # Even if user turned off medium confirmation, HIGH_RISK is unaffected
    clean_engine.set_user_medium_confirmation(user=user, require_confirmation=False)

    eval_res = clean_engine.evaluate_action(user=user, action=action)
    assert eval_res.risk_level == RiskLevel.HIGH_RISK
    assert eval_res.requires_approval is True
    assert eval_res.can_execute_immediately is False

    with pytest.raises(PermissionRequiredError) as exc_info:
        await clean_engine.execute_with_permission(
            user=user,
            action=action,
            func=lambda: "deleted",
        )
    assert exc_info.value.action == action
    assert exc_info.value.risk_level == RiskLevel.HIGH_RISK.value


# =============================================================================
# FAIL CLOSED WHEN PERMISSION INFORMATION IS MISSING
# =============================================================================


@pytest.mark.asyncio
async def test_fail_closed_when_permission_information_missing(clean_engine: PermissionEngine):
    """Requirement: The system must fail closed when permission information is missing."""
    # 1. Missing user
    eval_no_user = clean_engine.evaluate_action(user="", action="query:status")
    assert eval_no_user.fail_closed is True
    assert eval_no_user.requires_approval is True
    assert eval_no_user.can_execute_immediately is False

    with pytest.raises(MissingPermissionInfoError):
        await clean_engine.execute_with_permission(
            user="",
            action="query:status",
            func=lambda: "should_not_run",
        )

    # 2. Missing action
    eval_no_action = clean_engine.evaluate_action(user="alice", action="")
    assert eval_no_action.fail_closed is True
    assert eval_no_action.requires_approval is True

    with pytest.raises(MissingPermissionInfoError):
        await clean_engine.execute_with_permission(
            user="alice",
            action="",
            func=lambda: "should_not_run",
        )

    # 3. Unrecognized action with no matching policy
    eval_unknown = clean_engine.evaluate_action(user="alice", action="some_obscure_dangerous_op")
    assert eval_unknown.fail_closed is True
    assert eval_unknown.requires_approval is True
    assert eval_unknown.risk_level == RiskLevel.HIGH_RISK

    with pytest.raises(MissingPermissionInfoError):
        await clean_engine.execute_with_permission(
            user="alice",
            action="some_obscure_dangerous_op",
            func=lambda: "should_not_run",
        )

    # 4. Missing approval record for approval-requiring action
    with pytest.raises(PermissionRequiredError):
        await clean_engine.execute_with_permission(
            user="alice",
            action="goal:delete",
            func=lambda: "should_not_run",
            approval=None,
        )


# =============================================================================
# ACCEPTANCE CRITERIA
# =============================================================================


@pytest.mark.asyncio
async def test_acceptance_criteria_agent_cannot_execute_without_explicit_approval(
    clean_engine: PermissionEngine,
):
    """ACCEPTANCE CRITERIA:

    The agent cannot execute an action requiring approval without an explicit approval record.
    """
    user = "sarah"
    action = "payment:execute"
    payload = {"amount": 250.0, "currency": "USD", "recipient": "vendor_corp"}

    action_invoked = False

    def sensitive_payment_action(args):
        nonlocal action_invoked
        action_invoked = True
        return f"Payment of {args['amount']} {args['currency']} sent."

    # STEP 1: Agent attempts to execute without approval -> MUST FAIL CLOSED
    with pytest.raises(PermissionRequiredError) as exc_info:
        await clean_engine.execute_with_permission(
            user=user,
            action=action,
            func=sensitive_payment_action,
            parameters=payload,
        )

    assert exc_info.value.action == action
    # Verify the action callable was NEVER called
    assert action_invoked is False

    # STEP 2: Agent creates formal PermissionRequest
    req = clean_engine.create_permission_request(
        user=user,
        action=action,
        parameters=payload,
        reason="Quarterly server hosting fee",
    )
    assert req.status == RequestStatus.PENDING

    # Still cannot execute with just the request ID if unapproved
    with pytest.raises(PermissionRequiredError):
        await clean_engine.execute_with_permission(
            user=user,
            action=action,
            func=sensitive_payment_action,
            parameters=payload,
            request_id=req.id,
        )
    assert action_invoked is False

    # STEP 3: User grants explicit human approval
    approval = clean_engine.approve_request(
        request_id=req.id,
        user=user,
        reason="Approved quarterly server hosting payment",
    )
    assert approval.user == user
    assert approval.action == action
    assert approval.decision == DecisionType.APPROVED.value
    assert approval.is_explicit is True
    assert approval.consumed is False

    # STEP 4: Now agent executes with explicit approval record -> SUCCEEDS
    result, recorded_approval = await clean_engine.execute_with_permission(
        user=user,
        action=action,
        func=sensitive_payment_action,
        parameters=payload,
        approval=approval,
    )

    assert action_invoked is True
    assert result == "Payment of 250.0 USD sent."
    assert recorded_approval.consumed is True

    # STEP 5: Replay attack prevention: Attempting to reuse consumed approval fails
    with pytest.raises(InvalidApprovalError) as replay_exc:
        await clean_engine.execute_with_permission(
            user=user,
            action=action,
            func=sensitive_payment_action,
            parameters=payload,
            approval=approval,
        )
    assert "already been consumed" in replay_exc.value.message


# =============================================================================
# REJECTION & APPROVAL LIFECYCLE TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_rejection_lifecycle_and_blocking(clean_engine: PermissionEngine):
    """Verify rejection records reason and blocks subsequent approval/execution."""
    user = "elena"
    action = "goal:delete"

    req = clean_engine.create_permission_request(
        user=user,
        action=action,
        reason="User requested goal cleanup",
    )

    # Reject request
    rejection = clean_engine.reject_request(
        request_id=req.id,
        user=user,
        reason="Do not delete yet, goal is still in progress.",
    )
    assert rejection.user == user
    assert rejection.action == action
    assert rejection.decision == DecisionType.REJECTED.value
    assert rejection.reason == "Do not delete yet, goal is still in progress."

    updated_req = clean_engine.get_request(req.id)
    assert updated_req.status == RequestStatus.REJECTED

    # Cannot approve an already-rejected request
    with pytest.raises(InvalidApprovalError):
        clean_engine.approve_request(
            request_id=req.id,
            user=user,
            reason="Trying to approve anyway",
        )


def test_permission_request_expiration(clean_engine: PermissionEngine):
    """Verify expired requests cannot be approved."""
    user = "frank"
    req = clean_engine.create_permission_request(
        user=user,
        action="goal:delete",
        reason="Automated pruning",
        expires_in_seconds=-10.0,  # Expired in the past
    )

    # Listing pending filters out expired requests
    pending = clean_engine.list_pending_requests(user=user)
    assert req.id not in [p.id for p in pending]

    with pytest.raises(InvalidApprovalError) as exc_info:
        clean_engine.approve_request(
            request_id=req.id,
            user=user,
            reason="Approving stale request",
        )
    assert "expired" in exc_info.value.message


def test_unauthorized_user_cannot_approve(clean_engine: PermissionEngine):
    """Verify user B cannot approve user A's permission request."""
    user_a = "alice"
    user_b = "eve"

    req = clean_engine.create_permission_request(
        user=user_a,
        action="goal:delete",
        reason="Alice's request",
    )

    with pytest.raises(PermissionDeniedError):
        clean_engine.approve_request(
            request_id=req.id,
            user=user_b,
            reason="Eve attempting to authorize Alice's action",
        )


# =============================================================================
# DATABASE PERSISTENCE TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_permission_db_models_persistence(
    db_session: AsyncSession,
    test_user: User,
):
    """Verify ORM models for permission requests, approvals, rejections, and policies persist cleanly."""
    # 1. ActionPolicyModel
    policy = ActionPolicyModel(
        user_id=test_user.id,
        action_pattern="mcp:db:write",
        risk_level=RiskLevel.HIGH_RISK.value,
        description="Direct database write via MCP",
        require_confirmation_for_medium=True,
    )
    db_session.add(policy)
    await db_session.commit()

    # 2. PermissionRequestModel
    req = PermissionRequestModel(
        user_id=test_user.id,
        action="mcp:db:write",
        parameters={"table": "financials", "operation": "DROP"},
        risk_level=RiskLevel.HIGH_RISK.value,
        reason="Schema consolidation",
        status="PENDING",
    )
    db_session.add(req)
    await db_session.commit()
    await db_session.refresh(req)

    assert req.id is not None
    assert req.status == "PENDING"

    # 3. ApprovalModel
    approval = ApprovalModel(
        user_id=test_user.id,
        action="mcp:db:write",
        reason="Approved after manual backup",
        timestamp=datetime.now(UTC),
        decision="APPROVED",
        request_id=req.id,
        is_explicit=True,
        consumed=False,
    )
    db_session.add(approval)
    await db_session.commit()
    await db_session.refresh(approval)

    assert approval.id is not None
    assert approval.user_id == test_user.id
    assert approval.action == "mcp:db:write"
    assert approval.decision == "APPROVED"

    # 4. RejectionModel
    rejection = RejectionModel(
        user_id=test_user.id,
        action="mcp:db:write",
        reason="Rejected due to pending audit",
        timestamp=datetime.now(UTC),
        decision="REJECTED",
        request_id=req.id,
    )
    db_session.add(rejection)
    await db_session.commit()
    await db_session.refresh(rejection)

    assert rejection.id is not None
    assert rejection.decision == "REJECTED"

    # Query back
    stmt = select(ApprovalModel).where(ApprovalModel.user_id == test_user.id)
    res = await db_session.execute(stmt)
    records = res.scalars().all()
    assert len(records) == 1
    assert records[0].action == "mcp:db:write"


# =============================================================================
# REST API INTEGRATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_permissions_api_endpoints(
    db_session: AsyncSession,
    test_user: User,
    auth_token: str,
):
    """Test REST API endpoints for evaluation, requests, approval, rejection, and configuration."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_active_user] = lambda: test_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {auth_token}"}

        # 1. GET /api/v1/permissions/policies
        policies_resp = await client.get("/api/v1/permissions/policies", headers=headers)
        assert policies_resp.status_code == 200
        policies_data = policies_resp.json()
        assert len(policies_data) >= 3

        # 2. POST /api/v1/permissions/evaluate
        eval_resp = await client.post(
            "/api/v1/permissions/evaluate",
            json={"action": "goal:delete"},
            headers=headers,
        )
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        assert eval_data["risk_level"] == "HIGH_RISK"
        assert eval_data["requires_approval"] is True

        # 3. POST /api/v1/permissions/requests (Create pending request)
        create_req_resp = await client.post(
            "/api/v1/permissions/requests",
            json={
                "action": "goal:delete",
                "reason": "Clean up obsolete goal",
                "parameters": {"goal_id": "g-999"},
            },
            headers=headers,
        )
        assert create_req_resp.status_code == 201
        req_data = create_req_resp.json()
        req_id = req_data["id"]
        assert req_data["status"] == "PENDING"

        # 4. GET /api/v1/permissions/requests/pending
        pending_resp = await client.get("/api/v1/permissions/requests/pending", headers=headers)
        assert pending_resp.status_code == 200
        pending_list = pending_resp.json()
        assert any(p["id"] == req_id for p in pending_list)

        # 5. POST /api/v1/permissions/requests/{id}/approve
        approve_resp = await client.post(
            f"/api/v1/permissions/requests/{req_id}/approve",
            json={"reason": "Explicit approval by UI user"},
            headers=headers,
        )
        assert approve_resp.status_code == 200
        approval_data = approve_resp.json()
        assert approval_data["user"] == str(test_user.id)
        assert approval_data["action"] == "goal:delete"
        assert approval_data["decision"] == "APPROVED"
        assert approval_data["reason"] == "Explicit approval by UI user"
        assert approval_data["timestamp"] is not None

        # 6. GET /api/v1/permissions/approvals
        approvals_resp = await client.get("/api/v1/permissions/approvals", headers=headers)
        assert approvals_resp.status_code == 200
        approvals_list = approvals_resp.json()
        assert any(a["id"] == approval_data["id"] for a in approvals_list)

        # 7. POST /api/v1/permissions/config/medium-confirmation
        config_resp = await client.post(
            "/api/v1/permissions/config/medium-confirmation",
            json={"require_confirmation": False},
            headers=headers,
        )
        assert config_resp.status_code == 200
        assert config_resp.json()["require_confirmation_for_medium"] is False

    app.dependency_overrides.clear()
