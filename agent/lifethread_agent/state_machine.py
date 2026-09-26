import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

from lifethread_agent.models import AgentDecision, AgentRun
from lifethread_agent.types import AgentStatus

logger = logging.getLogger("lifethread.agent.state_machine")


class InvalidStateTransitionError(Exception):
    """Raised when an illegal status transition is attempted on an AgentRun."""

    pass


class LoopDetectedError(Exception):
    """Raised when an infinite loop or repetitive cycle of decisions is detected."""

    pass


class CancellationToken:
    """Cooperative cancellation token passed to runtime and step executions."""

    def __init__(self) -> None:
        self._is_cancelled: bool = False
        self._reason: str | None = None
        self._cancelled_at: datetime | None = None

    def cancel(self, reason: str = "Execution cancelled by caller") -> None:
        """Mark token as cancelled."""
        self._is_cancelled = True
        self._reason = reason
        self._cancelled_at = datetime.now(UTC)
        logger.info(f"Cancellation requested: {reason}")

    @property
    def is_cancelled(self) -> bool:
        return self._is_cancelled

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def cancelled_at(self) -> datetime | None:
        return self._cancelled_at


class LoopGuard:
    """Detects infinite loops, decision oscillations, and repetitive actions."""

    def __init__(self, repetition_threshold: int = 3, history_size: int = 10) -> None:
        self.repetition_threshold = repetition_threshold
        self.history_size = history_size
        self._decision_signatures: deque[str] = deque(maxlen=history_size)
        self._consecutive_count: int = 0
        self._last_signature: str | None = None

    def record_decision(self, decision: AgentDecision) -> None:
        """Record decision signature and raise LoopDetectedError if repetition threshold reached."""
        sig = decision.decision_signature()
        self._decision_signatures.append(sig)

        if sig == self._last_signature:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 1
            self._last_signature = sig

        if self._consecutive_count >= self.repetition_threshold:
            msg = (
                f"Loop detected: Agent repeated identical decision signature "
                f"[{sig}] {self._consecutive_count} consecutive times."
            )
            logger.error(msg)
            raise LoopDetectedError(msg)

    def reset(self) -> None:
        """Reset internal history."""
        self._decision_signatures.clear()
        self._consecutive_count = 0
        self._last_signature = None


class AgentStateMachine:
    """Manages legal lifecycle transitions and execution status changes for AgentRun."""

    # Explicit transition matrix
    _VALID_TRANSITIONS: dict[AgentStatus, set[AgentStatus]] = {
        AgentStatus.PENDING: {
            AgentStatus.RUNNING,
            AgentStatus.CANCELLED,
            AgentStatus.FAILED,
        },
        AgentStatus.RUNNING: {
            AgentStatus.PAUSED,
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.CANCELLED,
            AgentStatus.TIMEOUT,
        },
        AgentStatus.PAUSED: {
            AgentStatus.RUNNING,
            AgentStatus.CANCELLED,
            AgentStatus.FAILED,
        },
        AgentStatus.COMPLETED: set(),  # Terminal
        AgentStatus.FAILED: set(),  # Terminal
        AgentStatus.CANCELLED: set(),  # Terminal
        AgentStatus.TIMEOUT: set(),  # Terminal
    }

    @classmethod
    def can_transition(cls, current_status: AgentStatus, target_status: AgentStatus) -> bool:
        """Check whether a transition from current_status to target_status is permitted."""
        return target_status in cls._VALID_TRANSITIONS.get(current_status, set())

    @classmethod
    def transition(
        cls,
        run: AgentRun,
        target_status: AgentStatus,
        reason: str | None = None,
        error_details: str | None = None,
    ) -> None:
        """Execute a state transition on an AgentRun with timestamps and trace event."""
        if run.status == target_status:
            return

        if not cls.can_transition(run.status, target_status):
            msg = f"Illegal state transition from {run.status} to {target_status} for run {run.run_id}"
            logger.error(msg)
            raise InvalidStateTransitionError(msg)

        old_status = run.status
        run.status = target_status
        now = datetime.now(UTC)

        if target_status == AgentStatus.RUNNING and run.started_at is None:
            run.started_at = now

        if target_status in {
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.CANCELLED,
            AgentStatus.TIMEOUT,
        }:
            run.completed_at = now

        if error_details:
            run.error = error_details

        event: dict[str, Any] = {
            "type": "state_transition",
            "from_status": old_status.value,
            "to_status": target_status.value,
            "timestamp": now.isoformat(),
            "reason": reason,
        }
        if error_details:
            event["error"] = error_details

        run.trace.append(event)
        logger.info(
            f"Run [{run.run_id}] transitioned {old_status} -> {target_status} (reason: {reason})"
        )
