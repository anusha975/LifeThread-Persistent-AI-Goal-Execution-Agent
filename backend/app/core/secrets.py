"""Secret management and cryptographic configuration validation (Module 25)."""

import logging
import re
from typing import Any

from app.core.audit import SecurityAuditService, SecurityEventType

logger = logging.getLogger("lifethread.security.secrets")

KNOWN_INSECURE_PATTERNS = [
    r"dev_secret_key",
    r"change_in_production",
    r"lifethread_password_dev_only",
    r"mcp_internal_dev_secret",
    r"CHANGEME",
    r"secret123",
    r"^password$",
    r"^admin$",
    r"^123456$",
]


class InsecureSecretConfigurationError(ValueError):
    """Raised when application secrets fail security requirements in strict/production mode."""
    pass


def mask_secret(secret: str, visible_suffix_len: int = 4) -> str:
    """Mask sensitive string for safe logging and error reporting."""
    if not secret:
        return "[EMPTY]"
    if len(secret) <= visible_suffix_len:
        return "*" * len(secret)
    return "*" * (len(secret) - visible_suffix_len) + secret[-visible_suffix_len:]


def is_insecure_secret(val: str, min_length: int = 16) -> tuple[bool, str]:
    """Inspect secret against minimal length and known insecure placeholder patterns.

    Returns:
        tuple[bool, str]: (is_insecure, reason)
    """
    if not val or not val.strip():
        return True, "Secret value is empty"

    if len(val) < min_length:
        return True, f"Secret length ({len(val)}) is less than required minimum ({min_length})"

    for pattern in KNOWN_INSECURE_PATTERNS:
        if re.search(pattern, val, re.IGNORECASE):
            return True, f"Secret matches insecure default placeholder pattern: '{pattern}'"

    return False, ""


def validate_secrets_configuration(
    settings: Any,
    strict_override: bool | None = None,
) -> list[dict[str, Any]]:
    """Audit all application secrets and enforce security policies.

    In development mode, records audit warnings.
    In production mode or when STRICT_SECRET_VALIDATION is True, raises InsecureSecretConfigurationError.
    """
    violations: list[dict[str, Any]] = []

    # 1. JWT Secret Key
    jwt_secret = getattr(settings, "JWT_SECRET_KEY", "")
    is_insec, reason = is_insecure_secret(jwt_secret, min_length=32)
    if is_insec:
        violations.append({
            "secret_name": "JWT_SECRET_KEY",
            "reason": reason,
            "masked_value": mask_secret(jwt_secret),
        })

    # 2. Database Password (only applicable if PostgreSQL is configured)
    db_url = str(getattr(settings, "DATABASE_URL", "")).lower()
    if "postgres" in db_url:
        pg_password = getattr(settings, "POSTGRES_PASSWORD", "")
        is_insec, reason = is_insecure_secret(pg_password, min_length=8)
        if is_insec:
            violations.append({
                "secret_name": "POSTGRES_PASSWORD",
                "reason": reason,
                "masked_value": mask_secret(pg_password),
            })

    # 3. MCP Internal Shared Secret
    mcp_token = getattr(settings, "MCP_INTERNAL_TOKEN", "")
    is_insec, reason = is_insecure_secret(mcp_token, min_length=16)
    if is_insec:
        violations.append({
            "secret_name": "MCP_INTERNAL_TOKEN",
            "reason": reason,
            "masked_value": mask_secret(mcp_token),
        })

    strict = strict_override
    if strict is None:
        strict = getattr(settings, "STRICT_SECRET_VALIDATION", False)

    for v in violations:
        SecurityAuditService.record_event(
            event_type=SecurityEventType.INSECURE_SECRET_DETECTED,
            resource_type="secret_configuration",
            resource_id=v["secret_name"],
            action="VALIDATE_SECRETS",
            details={
                "reason": v["reason"],
                "masked_value": v["masked_value"],
                "strict_mode": strict,
            },
            severity="CRITICAL" if strict else "WARNING",
        )

    if violations:
        violation_messages = "; ".join(f"{v['secret_name']}: {v['reason']}" for v in violations)
        if strict:
            raise InsecureSecretConfigurationError(
                f"Production/Strict secret validation failed: {violation_messages}"
            )
        logger.warning(
            "Running with development/insecure secrets: %s. Configure environment variables in production.",
            violation_messages,
        )

    return violations
