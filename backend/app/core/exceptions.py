import logging
from typing import Any

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.error import ErrorDetail, ErrorResponse

logger = logging.getLogger("lifethread.exceptions")


class LifeThreadException(Exception):
    """Base application exception for LifeThread."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class EntityNotFoundException(LifeThreadException):
    """Raised when a requested resource is not found."""

    def __init__(self, message: str = "Resource not found", details: Any | None = None) -> None:
        super().__init__(
            message=message,
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )


class BadRequestException(LifeThreadException):
    """Raised for malformed client requests."""

    def __init__(self, message: str = "Bad request", details: Any | None = None) -> None:
        super().__init__(
            message=message,
            code="BAD_REQUEST",
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )


def get_request_id_from_request(request: Request) -> str | None:
    """Safely obtain request ID from request state or header."""
    return getattr(request.state, "request_id", request.headers.get("X-Request-ID"))


async def lifethread_exception_handler(request: Request, exc: LifeThreadException) -> JSONResponse:
    """Handle domain-level LifeThread exceptions."""
    request_id = get_request_id_from_request(request)
    logger.warning(
        f"Domain exception [{exc.code}] on {request.method} {request.url.path}: {exc.message}",
        extra={"request_id": request_id, "details": exc.details},
    )
    payload = ErrorResponse(
        error=ErrorDetail(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=request_id,
        )
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle standard Starlette / FastAPI HTTPExceptions (including 404 Not Found)."""
    request_id = get_request_id_from_request(request)
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_SERVER_ERROR",
    }
    error_code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
    message = str(exc.detail) if exc.detail else "An HTTP error occurred"

    payload = ErrorResponse(
        error=ErrorDetail(
            code=error_code,
            message=message,
            details=None,
            request_id=request_id,
        )
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle FastAPI request validation errors (422 Unprocessable Entity)."""
    request_id = get_request_id_from_request(request)
    details = jsonable_encoder(exc.errors())
    payload = ErrorResponse(
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=details,
            request_id=request_id,
        )
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=payload.model_dump(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unexpected internal server errors."""
    request_id = get_request_id_from_request(request)
    logger.exception(
        f"Unhandled server error on {request.method} {request.url.path}: {exc}",
        extra={"request_id": request_id},
    )
    payload = ErrorResponse(
        error=ErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal server error occurred",
            details=None,
            request_id=request_id,
        )
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=payload.model_dump(),
    )
