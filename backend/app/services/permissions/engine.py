"""Engine and gatekeeper for Module 24 Human-in-the-Loop Permission System."""

import inspect
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.permissions.exceptions import (
    InvalidApprovalError,
    MissingPermissionInfoError,
    PermissionDeniedError,
    PermissionRequiredError,
    RequestNotFoundError,
)
from app.services.permissions.models import (
    Approval,
    DecisionType,
    PermissionEvaluationResult,
    PermissionRequest,
    Rejection,
    RequestStatus,
    RiskLevel,
)
from app.services.permissions.policy_registry import PolicyRegistry

logger = logging.getLogger(__name__)


class PermissionEngine:
    """Core engine enforcing human-in-the-loop permission checks.

    Invariants:
    1. LOW_RISK: May execute automatically.
    2. MEDIUM_RISK: May require configurable confirmation.
    3. HIGH_RISK: Always requires explicit user approval.
    4. Every approval must record: user, action, reason, timestamp, decision.
    5. The system must fail closed when permission information is missing.
    6. ACCEPTANCE CRITERIA: The agent cannot execute an action requiring approval
       without an explicit approval record.
    """

    def __init__(
        self,
        policy_registry: PolicyRegistry | None = None,
        default_medium_confirmation: bool = True,
    ) -> None:
        self.registry = policy_registry or PolicyRegistry()
        self.default_medium_confirmation = default_medium_confirmation
        self._requests: dict[str, PermissionRequest] = {}
        self._approvals: dict[str, Approval] = {}
        self._rejections: dict[str, Rejection] = {}
        # User-specific confirmation settings for medium risk actions
        self._user_medium_confirmation_settings: dict[str, bool] = {}

    def set_user_medium_confirmation(self, user: str, require_confirmation: bool) -> None:
        """Configure confirmation requirements for medium-risk actions for a specific user."""
        self._user_medium_confirmation_settings[user] = require_confirmation

    # =========================================================================
    # EVALUATION (FAIL-CLOSED)
    # =========================================================================

    def evaluate_action(
        self,
        user: str | None = None,
        action: str | None = None,
        parameters: dict[str, Any] | None = None,
        confirmation_override: bool | None = None,
        *,
        user_id: Any | None = None,
    ) -> PermissionEvaluationResult:
        """Evaluate an action against policies to determine risk level and approval requirements.

        Fails closed if user, action, or matching policy is missing.
        """
        if user is None and user_id is not None:
            user = str(user_id)

        # Rule 5: Fail closed when permission information is missing
        if not user or not str(user).strip():
            logger.warning("Permission evaluation failed: Missing user. Failing closed.")
            return PermissionEvaluationResult(
                action=action or "UNKNOWN",
                risk_level=RiskLevel.HIGH_RISK,
                requires_approval=True,
                can_execute_immediately=False,
                policy_matched=None,
                reason="Missing user information. Failing closed.",
                fail_closed=True,
            )

        if not action or not str(action).strip():
            logger.warning("Permission evaluation failed: Missing action. Failing closed.")
            return PermissionEvaluationResult(
                action="UNKNOWN",
                risk_level=RiskLevel.HIGH_RISK,
                requires_approval=True,
                can_execute_immediately=False,
                policy_matched=None,
                reason="Missing action information. Failing closed.",
                fail_closed=True,
            )

        clean_user = str(user).strip()
        clean_action = str(action).strip()

        # Match policy
        policy = self.registry.match_policy(clean_action)
        if policy is None:
            # Rule 5: Unrecognized actions fail closed
            logger.warning(
                "No policy found for action '%s'. Failing closed as HIGH_RISK.",
                clean_action,
            )
            return PermissionEvaluationResult(
                action=clean_action,
                risk_level=RiskLevel.HIGH_RISK,
                requires_approval=True,
                can_execute_immediately=False,
                policy_matched=None,
                reason=f"No matching permission policy found for action '{clean_action}'. Failing closed.",
                fail_closed=True,
            )

        # 1. LOW_RISK: May execute automatically
        if policy.risk_level == RiskLevel.LOW_RISK:
            can_auto = policy.allow_auto_approval_for_low
            return PermissionEvaluationResult(
                action=clean_action,
                risk_level=RiskLevel.LOW_RISK,
                requires_approval=not can_auto,
                can_execute_immediately=can_auto,
                policy_matched=policy,
                reason="Low risk action permitted to execute automatically."
                if can_auto
                else "Low risk action configured to require confirmation.",
                fail_closed=False,
            )

        # 2. MEDIUM_RISK: May require configurable confirmation
        elif policy.risk_level == RiskLevel.MEDIUM_RISK:
            # Check hierarchy of confirmation settings:
            # 1) explicit method override
            # 2) user-specific configuration
            # 3) policy-level configuration
            # 4) default engine configuration
            if confirmation_override is not None:
                requires_confirm = confirmation_override
            elif clean_user in self._user_medium_confirmation_settings:
                requires_confirm = self._user_medium_confirmation_settings[clean_user]
            elif policy.require_confirmation_for_medium is not None:
                requires_confirm = policy.require_confirmation_for_medium
            else:
                # If confirmation setting is missing or undefined -> fail closed!
                requires_confirm = True

            return PermissionEvaluationResult(
                action=clean_action,
                risk_level=RiskLevel.MEDIUM_RISK,
                requires_approval=requires_confirm,
                can_execute_immediately=not requires_confirm,
                policy_matched=policy,
                reason="Medium risk action requiring user confirmation."
                if requires_confirm
                else "Medium risk action configured for automatic execution.",
                fail_closed=False,
            )

        # 3. HIGH_RISK: Always requires explicit user approval
        elif policy.risk_level == RiskLevel.HIGH_RISK:
            return PermissionEvaluationResult(
                action=clean_action,
                risk_level=RiskLevel.HIGH_RISK,
                requires_approval=True,
                can_execute_immediately=False,
                policy_matched=policy,
                reason="High risk action always requires explicit user approval.",
                fail_closed=False,
            )

        # Any unhandled risk level fails closed
        return PermissionEvaluationResult(
            action=clean_action,
            risk_level=RiskLevel.HIGH_RISK,
            requires_approval=True,
            can_execute_immediately=False,
            policy_matched=policy,
            reason="Unrecognized risk level. Failing closed.",
            fail_closed=True,
        )

    # =========================================================================
    # PERMISSION REQUEST CREATION
    # =========================================================================

    def create_permission_request(
        self,
        user: str,
        action: str,
        reason: str,
        parameters: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        expires_in_seconds: float | None = 3600.0,
    ) -> PermissionRequest:
        """Create a pending permission request for a user to authorize."""
        if not user or not str(user).strip():
            raise MissingPermissionInfoError(
                "Cannot create permission request without a valid user."
            )
        if not action or not str(action).strip():
            raise MissingPermissionInfoError("Cannot create permission request without an action.")

        clean_user = str(user).strip()
        clean_action = str(action).strip()

        eval_res = self.evaluate_action(clean_user, clean_action, parameters)

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=expires_in_seconds) if expires_in_seconds else None

        req = PermissionRequest(
            user_id=clean_user,
            action=clean_action,
            parameters=parameters or {},
            risk_level=eval_res.risk_level,
            reason=reason,
            status=RequestStatus.PENDING,
            context=context or {},
            created_at=now,
            expires_at=expires_at,
        )

        self._requests[req.id] = req
        logger.info(
            "Created PermissionRequest '%s' for action '%s' [%s] (user=%s)",
            req.id,
            req.action,
            req.risk_level.value,
            req.user_id,
        )
        return req

    def get_request(self, request_id: str) -> PermissionRequest:
        """Retrieve a PermissionRequest by ID or raise RequestNotFoundError."""
        req = self._requests.get(request_id)
        if not req:
            raise RequestNotFoundError(request_id)
        return req

    def list_pending_requests(self, user: str | None = None) -> list[PermissionRequest]:
        """List all pending permission requests, optionally filtered by user."""
        now = datetime.now(UTC)
        pending: list[PermissionRequest] = []
        for req in self._requests.values():
            # Check expiration
            if req.status == RequestStatus.PENDING and req.expires_at and now > req.expires_at:
                req.status = RequestStatus.EXPIRED
                continue

            if req.status == RequestStatus.PENDING:
                if user is None or req.user_id == str(user).strip():
                    pending.append(req)
        return pending

    # =========================================================================
    # APPROVAL & REJECTION LIFECYCLE
    # =========================================================================

    def approve_request(
        self,
        request_id: str,
        user: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> Approval:
        """Authorize a pending permission request, recording an explicit Approval record.

        Requirement: Every approval must record:
        - user
        - action
        - reason
        - timestamp
        - decision
        """
        if not user or not str(user).strip():
            raise MissingPermissionInfoError("Approving user must be specified.")

        clean_user = str(user).strip()
        req = self.get_request(request_id)

        if req.user_id != clean_user:
            raise PermissionDeniedError(
                action=req.action,
                reason=f"User '{clean_user}' is not authorized to approve request for '{req.user_id}'.",
            )

        now = datetime.now(UTC)
        if req.expires_at and now > req.expires_at:
            req.status = RequestStatus.EXPIRED
            raise InvalidApprovalError("Permission request has expired and cannot be approved.")

        if req.status != RequestStatus.PENDING:
            raise InvalidApprovalError(
                f"Permission request is in status '{req.status.value}' and cannot be approved."
            )

        approval = Approval(
            user=clean_user,
            action=req.action,
            reason=reason or "Explicit user approval",
            timestamp=now,
            decision=DecisionType.APPROVED.value,
            request_id=req.id,
            is_explicit=True,
            metadata=metadata or {},
        )

        req.status = RequestStatus.APPROVED
        req.approval_id = approval.id

        self._approvals[approval.id] = approval
        logger.info(
            "PermissionRequest '%s' APPROVED by '%s' for action '%s' [Approval ID: %s]",
            req.id,
            clean_user,
            req.action,
            approval.id,
        )
        return approval

    def reject_request(
        self,
        request_id: str,
        user: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> Rejection:
        """Deny a pending permission request, recording an explicit Rejection record."""
        if not user or not str(user).strip():
            raise MissingPermissionInfoError("Rejecting user must be specified.")

        clean_user = str(user).strip()
        req = self.get_request(request_id)

        if req.user_id != clean_user:
            raise PermissionDeniedError(
                action=req.action,
                reason=f"User '{clean_user}' is not authorized to reject request for '{req.user_id}'.",
            )

        now = datetime.now(UTC)
        if req.status != RequestStatus.PENDING:
            raise InvalidApprovalError(
                f"Permission request is in status '{req.status.value}' and cannot be rejected."
            )

        rejection = Rejection(
            user=clean_user,
            action=req.action,
            reason=reason or "Explicit user rejection",
            timestamp=now,
            decision=DecisionType.REJECTED.value,
            request_id=req.id,
            metadata=metadata or {},
        )

        req.status = RequestStatus.REJECTED
        req.rejection_id = rejection.id

        self._rejections[rejection.id] = rejection
        logger.info(
            "PermissionRequest '%s' REJECTED by '%s' for action '%s' [Rejection ID: %s]",
            req.id,
            clean_user,
            req.action,
            rejection.id,
        )
        return rejection

    def get_approval(self, approval_id: str) -> Approval | None:
        """Retrieve an Approval record by ID."""
        return self._approvals.get(approval_id)

    def list_approvals(self, user: str | None = None) -> list[Approval]:
        """List all approvals, optionally filtered by user."""
        if user is None:
            return list(self._approvals.values())
        clean_user = str(user).strip()
        return [a for a in self._approvals.values() if a.user == clean_user]

    # =========================================================================
    # EXECUTION GATEKEEPER (ACCEPTANCE CRITERIA)
    # =========================================================================

    async def execute_with_permission(
        self,
        user: str,
        action: str,
        func: Callable[..., Any],
        parameters: dict[str, Any] | None = None,
        approval: Approval | None = None,
        request_id: str | None = None,
        confirmation_override: bool | None = None,
    ) -> tuple[Any, Approval]:
        """Execute an action strictly guarded by the permission policy.

        ACCEPTANCE CRITERIA:
        The agent cannot execute an action requiring approval without an explicit approval record.

        Returns:
            tuple[Any, Approval]: (result_of_func, verified_approval_record)

        Raises:
            MissingPermissionInfoError: If user, action, or policy is missing (fails closed).
            PermissionRequiredError: If action requires approval and no valid explicit approval exists.
            InvalidApprovalError: If approval is invalid, mismatched, or previously consumed.
        """
        # 1. Missing information check (Fail-closed)
        if not user or not str(user).strip():
            logger.error("execute_with_permission failed: Missing user information.")
            raise MissingPermissionInfoError(
                "Cannot execute action without user information. Failing closed."
            )

        if not action or not str(action).strip():
            logger.error("execute_with_permission failed: Missing action information.")
            raise MissingPermissionInfoError(
                "Cannot execute action without action name. Failing closed."
            )

        clean_user = str(user).strip()
        clean_action = str(action).strip()
        params = parameters or {}

        # 2. Evaluate policy
        eval_res = self.evaluate_action(clean_user, clean_action, params, confirmation_override)

        # Fail closed on unrecognized action or missing policy
        if eval_res.fail_closed or eval_res.policy_matched is None:
            logger.error(
                "execute_with_permission: Action '%s' has missing permission policy. Failing closed.",
                clean_action,
            )
            raise MissingPermissionInfoError(
                f"No permission policy registered for '{clean_action}'. Failing closed."
            )

        # 3. Handle actions requiring approval (HIGH_RISK or confirmation-enabled MEDIUM_RISK)
        if eval_res.requires_approval:
            # Locate approval record if request_id supplied
            resolved_approval = approval
            if resolved_approval is None and request_id:
                req = self.get_request(request_id)
                if req.approval_id:
                    resolved_approval = self.get_approval(req.approval_id)

            # CRITICAL ACCEPTANCE CRITERIA CHECK:
            # Cannot execute an action requiring approval without an explicit approval record!
            if resolved_approval is None:
                logger.warning(
                    "EXECUTION BLOCKED: Action '%s' requires approval, but no approval record was provided.",
                    clean_action,
                )
                raise PermissionRequiredError(
                    action=clean_action,
                    risk_level=eval_res.risk_level.value,
                    request_id=request_id,
                )

            # Verify the approval record
            if resolved_approval.user != clean_user:
                raise InvalidApprovalError(
                    f"Approval user '{resolved_approval.user}' does not match executing user '{clean_user}'."
                )

            if resolved_approval.action != clean_action:
                raise InvalidApprovalError(
                    f"Approval action '{resolved_approval.action}' does not match target action '{clean_action}'."
                )

            if resolved_approval.decision != DecisionType.APPROVED.value:
                raise InvalidApprovalError(
                    f"Approval record decision is '{resolved_approval.decision}', not APPROVED."
                )

            if not resolved_approval.is_explicit:
                raise InvalidApprovalError(
                    f"Action '{clean_action}' [{eval_res.risk_level.value}] strictly requires an EXPLICIT user approval record."
                )

            if resolved_approval.consumed:
                raise InvalidApprovalError(
                    f"Approval record '{resolved_approval.id}' has already been consumed."
                )

            # Validate that all required fields are present
            assert resolved_approval.user, "Approval must record user"
            assert resolved_approval.action, "Approval must record action"
            assert resolved_approval.reason, "Approval must record reason"
            assert resolved_approval.timestamp, "Approval must record timestamp"
            assert resolved_approval.decision, "Approval must record decision"

            # Mark approval consumed to prevent replay attacks
            resolved_approval.consumed = True
            active_approval = resolved_approval

        # 4. Handle LOW_RISK (or MEDIUM_RISK configured for automatic execution)
        else:
            # May execute automatically. Generate an AUTO_APPROVED approval record
            # satisfying: Every approval must record: user, action, reason, timestamp, decision
            active_approval = Approval(
                user=clean_user,
                action=clean_action,
                reason=f"Auto-approved {eval_res.risk_level.value} action according to policy",
                timestamp=datetime.now(UTC),
                decision=DecisionType.AUTO_APPROVED.value,
                is_explicit=False,
                consumed=True,
                metadata={
                    "risk_level": eval_res.risk_level.value,
                    "policy_id": eval_res.policy_matched.id if eval_res.policy_matched else None,
                },
            )
            self._approvals[active_approval.id] = active_approval

        # 5. Execute action callable safely
        try:
            res = func(params) if len(inspect.signature(func).parameters) > 0 else func()
            if inspect.isawaitable(res):
                res = await res
            return res, active_approval
        except Exception as e:
            logger.error("Error executing permitted action '%s': %s", clean_action, e)
            raise


# Global singleton instance for app-wide use
permission_engine = PermissionEngine()
