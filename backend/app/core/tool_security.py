"""Tool security and malicious argument defense (Module 25).

Enforces tool permissions and intercepts malicious arguments such as path traversal,
command injection, SQL injection strings, and dangerous URL protocols before execution.
"""

import re
from typing import Any

from app.core.audit import SecurityAuditService, SecurityEventType

# Patterns representing malicious input vectors in tool parameters
MALICIOUS_ARGUMENT_PATTERNS: list[tuple[str, str]] = [
    # Path traversal
    (r"(?i)(\.\.[/\\]|%2e%2e[/\\]|%2e%2e%2f)", "PATH_TRAVERSAL"),
    (r"(?i)(/etc/(passwd|shadow|hosts)|[a-z]:\\windows\\system32)", "SENSITIVE_SYSTEM_PATH"),
    # Command injection
    (r"(?i)[;&|`$]\s*(rm\s+-rf|del\s+|format\s+|shutdown|curl|wget|nc\s+|bash|sh|powershell)", "COMMAND_INJECTION"),
    (r"(?i)\b(curl|wget)\s+https?://", "OUTBOUND_COMMAND_PIPE"),
    # SQL injection heuristics in parameters
    (r"(?i)('\s*or\s*'1'\s*=\s*'1|;\s*drop\s+table\b|\bunion\s+select\b|--\s*$)", "SQL_INJECTION"),
    # Dangerous URI schemes
    (r"(?i)\b(file|gopher|dict|javascript|data)://", "DANGEROUS_URI_SCHEME"),
    # Null byte injection
    (r"\x00|%00", "NULL_BYTE_INJECTION"),
]


class MaliciousArgumentDetector:
    """Detects and blocks hostile, malicious arguments in agent and MCP tool invocations."""

    @classmethod
    def scan_value(cls, val: Any) -> tuple[bool, str | None, str | None]:
        """Recursively scan a value (str, dict, list) for hostile argument patterns.

        Returns:
            tuple[bool, str | None, str | None]: (is_malicious, classification, matched_snippet)
        """
        if isinstance(val, str):
            for pattern, classification in MALICIOUS_ARGUMENT_PATTERNS:
                match = re.search(pattern, val)
                if match:
                    return True, classification, match.group(0)

        elif isinstance(val, dict):
            for k, v in val.items():
                is_mal, cls_name, snip = cls.scan_value(k)
                if is_mal:
                    return True, cls_name, snip
                is_mal, cls_name, snip = cls.scan_value(v)
                if is_mal:
                    return True, cls_name, snip

        elif isinstance(val, (list, tuple, set)):
            for item in val:
                is_mal, cls_name, snip = cls.scan_value(item)
                if is_mal:
                    return True, cls_name, snip

        return False, None, None

    @classmethod
    def validate_tool_arguments(
        cls,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: str | None = None,
        record_audit: bool = True,
    ) -> tuple[bool, str | None]:
        """Validate tool arguments against malicious injection attacks.

        Returns:
            tuple[bool, str | None]: (is_safe, error_message_if_blocked)
        """
        is_mal, classification, snippet = cls.scan_value(arguments)
        if is_mal:
            err_msg = (
                f"Malicious tool argument detected in '{tool_name}': "
                f"classification={classification}, snippet='{snippet}'"
            )
            if record_audit:
                SecurityAuditService.record_event(
                    event_type=SecurityEventType.MALICIOUS_TOOL_ARGUMENTS,
                    user_id=user_id,
                    resource_type="tool",
                    resource_id=tool_name,
                    action="EXECUTE_TOOL",
                    details={
                        "classification": classification,
                        "snippet": snippet,
                        "arguments": str(arguments)[:200],
                    },
                    severity="CRITICAL",
                )
            return False, err_msg

        return True, None
