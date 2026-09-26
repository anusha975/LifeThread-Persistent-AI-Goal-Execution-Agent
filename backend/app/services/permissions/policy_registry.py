"""Policy registry for Module 24 Human-in-the-Loop Permission System."""

import logging
from fnmatch import fnmatch

from app.services.permissions.models import ActionPolicy, RiskLevel

logger = logging.getLogger(__name__)


DEFAULT_SYSTEM_POLICIES: list[ActionPolicy] = [
    # -------------------------------------------------------------
    # LOW_RISK: May execute automatically
    # -------------------------------------------------------------
    ActionPolicy(
        action_pattern="query:*",
        risk_level=RiskLevel.LOW_RISK,
        description="Read-only data queries and status checks",
        allow_auto_approval_for_low=True,
    ),
    ActionPolicy(
        action_pattern="read:*",
        risk_level=RiskLevel.LOW_RISK,
        description="Read-only information retrieval",
        allow_auto_approval_for_low=True,
    ),
    ActionPolicy(
        action_pattern="mcp:calculate",
        risk_level=RiskLevel.LOW_RISK,
        description="Local mathematical or formatting calculations",
        allow_auto_approval_for_low=True,
    ),
    ActionPolicy(
        action_pattern="mcp:get_*",
        risk_level=RiskLevel.LOW_RISK,
        description="Safe read operations via MCP",
        allow_auto_approval_for_low=True,
    ),
    ActionPolicy(
        action_pattern="memory:retrieve",
        risk_level=RiskLevel.LOW_RISK,
        description="Reading user memories for context",
        allow_auto_approval_for_low=True,
    ),
    # -------------------------------------------------------------
    # MEDIUM_RISK: May require configurable confirmation
    # -------------------------------------------------------------
    ActionPolicy(
        action_pattern="goal:update_title",
        risk_level=RiskLevel.MEDIUM_RISK,
        description="Updating goal title or descriptive metadata",
        require_confirmation_for_medium=True,
    ),
    ActionPolicy(
        action_pattern="plan:reschedule_task",
        risk_level=RiskLevel.MEDIUM_RISK,
        description="Adjusting task scheduling or deadlines",
        require_confirmation_for_medium=True,
    ),
    ActionPolicy(
        action_pattern="plan:reorder",
        risk_level=RiskLevel.MEDIUM_RISK,
        description="Reordering execution sequence of planned items",
        require_confirmation_for_medium=False,  # Can be configured false
    ),
    ActionPolicy(
        action_pattern="document:export",
        risk_level=RiskLevel.MEDIUM_RISK,
        description="Exporting summary reports or artifacts",
        require_confirmation_for_medium=True,
    ),
    ActionPolicy(
        action_pattern="mcp:write_temp_file",
        risk_level=RiskLevel.MEDIUM_RISK,
        description="Writing temporary artifacts to workspace",
        require_confirmation_for_medium=True,
    ),
    # -------------------------------------------------------------
    # HIGH_RISK: Always require explicit user approval
    # -------------------------------------------------------------
    ActionPolicy(
        action_pattern="goal:delete",
        risk_level=RiskLevel.HIGH_RISK,
        description="Irreversible deletion of a user goal and its roadmap",
    ),
    ActionPolicy(
        action_pattern="plan:abandon",
        risk_level=RiskLevel.HIGH_RISK,
        description="Abandoning active roadmap or plan",
    ),
    ActionPolicy(
        action_pattern="payment:*",
        risk_level=RiskLevel.HIGH_RISK,
        description="Initiating or authorizing financial transactions",
    ),
    ActionPolicy(
        action_pattern="email:send_external",
        risk_level=RiskLevel.HIGH_RISK,
        description="Sending external emails or notifications to third parties",
    ),
    ActionPolicy(
        action_pattern="database:drop_*",
        risk_level=RiskLevel.HIGH_RISK,
        description="Destructive database modifications",
    ),
    ActionPolicy(
        action_pattern="mcp:fs:delete_*",
        risk_level=RiskLevel.HIGH_RISK,
        description="Destructive filesystem actions via MCP",
    ),
]


class PolicyRegistry:
    """In-memory and persistent registry for matching action names to ActionPolicies."""

    def __init__(self, initial_policies: list[ActionPolicy] | None = None) -> None:
        self._policies: list[ActionPolicy] = []
        policies = initial_policies if initial_policies is not None else DEFAULT_SYSTEM_POLICIES
        for p in policies:
            self.register_policy(p)

    def register_policy(self, policy: ActionPolicy) -> None:
        """Register a new action policy, prepending it to prioritize recent additions."""
        # Remove any existing policy with the exact same ID or action pattern
        self._policies = [p for p in self._policies if p.id != policy.id]
        self._policies.insert(0, policy)
        logger.debug(
            "Registered policy '%s' for action '%s' [%s]",
            policy.id,
            policy.action_pattern,
            policy.risk_level.value,
        )

    def list_policies(self) -> list[ActionPolicy]:
        """Return a copy of all registered policies."""
        return list(self._policies)

    def match_policy(self, action: str) -> ActionPolicy | None:
        """Find the most specific matching policy for an action name.

        Evaluation order:
        1. Exact match
        2. Wildcard pattern match
        3. Returns None if no policy matches (triggering fail-closed)
        """
        if not action or not action.strip():
            return None

        clean_action = action.strip()

        # 1. Exact match first
        for policy in self._policies:
            if policy.action_pattern == clean_action:
                return policy

        # 2. Glob pattern match
        for policy in self._policies:
            if fnmatch(clean_action, policy.action_pattern):
                return policy

        return None

    def clear(self) -> None:
        """Clear all registered policies."""
        self._policies.clear()

    def reset_defaults(self) -> None:
        """Reset to default system policies."""
        self._policies.clear()
        for p in DEFAULT_SYSTEM_POLICIES:
            self.register_policy(p)
