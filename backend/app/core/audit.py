"""Security auditing and structured event logging for Module 25."""

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("lifethread.security.audit")


class SecurityEventType(StrEnum):
    """Categorical security event classifications."""

    # Authorization & Access
    ACCESS_GRANTED = "ACCESS_GRANTED"
    UNAUTHORIZED_ACCESS_ATTEMPT = "UNAUTHORIZED_ACCESS_ATTEMPT"
    CROSS_USER_ACCESS_BLOCKED = "CROSS_USER_ACCESS_BLOCKED"
    IDOR_ATTEMPT_DETECTED = "IDOR_ATTEMPT_DETECTED"

    # Authentication & Tokens
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REVOKED_USED = "TOKEN_REVOKED_USED"
    TOKEN_MALFORMED = "TOKEN_MALFORMED"

    # Rate Limiting
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # Prompt Injection & Input Defenses
    PROMPT_INJECTION_DETECTED = "PROMPT_INJECTION_DETECTED"
    MALICIOUS_INPUT_BLOCKED = "MALICIOUS_INPUT_BLOCKED"
    FILE_UPLOAD_REJECTED = "FILE_UPLOAD_REJECTED"

    # Tool & MCP Security
    TOOL_PERMISSION_DENIED = "TOOL_PERMISSION_DENIED"
    MALICIOUS_TOOL_ARGUMENTS = "MALICIOUS_TOOL_ARGUMENTS"
    MCP_AUTH_FAILURE = "MCP_AUTH_FAILURE"

    # Secret & Config
    INSECURE_SECRET_DETECTED = "INSECURE_SECRET_DETECTED"


class SecurityAuditLog(BaseModel):
    """Structured security audit log entry."""

    model_config = ConfigDict(extra="ignore")

    event_type: SecurityEventType
    user_id: str | None = None
    ip_address: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    action: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    severity: str = "INFO"  # INFO, WARNING, CRITICAL


class SecurityAuditService:
    """Central service for recording structured security events."""

    _events: list[SecurityAuditLog] = []
    _max_in_memory: int = 1000

    @classmethod
    def record_event(
        cls,
        event_type: SecurityEventType,
        user_id: str | None = None,
        ip_address: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        action: str | None = None,
        details: dict[str, Any] | None = None,
        severity: str = "WARNING",
    ) -> SecurityAuditLog:
        """Record and log a structured security audit event."""
        log_entry = SecurityAuditLog(
            event_type=event_type,
            user_id=user_id,
            ip_address=ip_address,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            details=details or {},
            severity=severity,
        )

        cls._events.append(log_entry)
        if len(cls._events) > cls._max_in_memory:
            cls._events.pop(0)

        log_fn = (
            logger.critical
            if severity == "CRITICAL"
            else logger.warning
            if severity == "WARNING"
            else logger.info
        )
        log_fn(
            "AUDIT [%s] user=%s ip=%s resource=%s:%s action=%s details=%s",
            event_type.value,
            user_id or "anonymous",
            ip_address or "unknown",
            resource_type or "none",
            resource_id or "none",
            action or "none",
            details or {},
        )

        return log_entry

    @classmethod
    def get_events(
        cls,
        user_id: str | None = None,
        event_type: SecurityEventType | None = None,
        limit: int = 50,
    ) -> list[SecurityAuditLog]:
        """Query security audit logs."""
        filtered = cls._events
        if user_id:
            filtered = [e for e in filtered if e.user_id == user_id]
        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]
        return filtered[-limit:]

    @classmethod
    def clear(cls) -> None:
        """Clear recorded events (for testing)."""
        cls._events.clear()
