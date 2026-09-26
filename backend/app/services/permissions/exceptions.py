"""Exceptions for Module 24 Human-in-the-Loop Permission System."""


class PermissionSystemError(Exception):
    """Base exception for all permission system errors."""

    pass


class MissingPermissionInfoError(PermissionSystemError):
    """Raised when permission information is missing, triggering a fail-closed response."""

    def __init__(self, message: str = "Permission information is missing. Failing closed."):
        super().__init__(message)
        self.message = message


class PermissionRequiredError(PermissionSystemError):
    """Raised when an action requires approval but has no valid explicit approval record."""

    def __init__(
        self,
        action: str,
        risk_level: str,
        request_id: str | None = None,
        message: str | None = None,
    ):
        msg = (
            message
            or f"Action '{action}' [{risk_level}] requires explicit user approval before execution."
        )
        super().__init__(msg)
        self.action = action
        self.risk_level = risk_level
        self.request_id = request_id


class PermissionDeniedError(PermissionSystemError):
    """Raised when an action was explicitly rejected or blocked by security policy."""

    def __init__(self, action: str, reason: str = "Action authorization was denied."):
        super().__init__(f"Permission denied for '{action}': {reason}")
        self.action = action
        self.reason = reason


class InvalidApprovalError(PermissionSystemError):
    """Raised when an approval record is invalid, expired, mismatching, or already consumed."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class RequestNotFoundError(PermissionSystemError):
    """Raised when a referenced PermissionRequest cannot be found."""

    def __init__(self, request_id: str):
        super().__init__(f"PermissionRequest '{request_id}' not found.")
        self.request_id = request_id
