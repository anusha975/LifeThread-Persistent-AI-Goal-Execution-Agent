from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detailed error object representation."""

    code: str = Field(..., description="Machine-readable error classification code")
    message: str = Field(..., description="Human-readable error description")
    details: Any | None = Field(
        default=None, description="Optional granular error details or validation context"
    )
    request_id: str | None = Field(
        default=None, description="Request identifier for distributed tracing"
    )


class ErrorResponse(BaseModel):
    """Standardized top-level API error response."""

    error: ErrorDetail
