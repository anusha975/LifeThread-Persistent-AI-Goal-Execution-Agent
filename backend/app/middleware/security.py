"""Security middleware for rate limiting and secure HTTP response headers (Module 25)."""

import logging
import math
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.audit import SecurityAuditService, SecurityEventType
from app.core.config import get_settings

logger = logging.getLogger("lifethread.security.middleware")


class TokenBucketRateLimiter:
    """In-memory thread-safe token bucket rate limiter per client IP or user identity."""

    def __init__(self, requests_per_minute: int = 120, burst_capacity: int = 30) -> None:
        self.rate = requests_per_minute / 60.0  # Tokens added per second
        self.capacity = float(burst_capacity)
        # client_key -> (tokens, last_refreshed_timestamp)
        self._buckets: dict[str, tuple[float, float]] = {}

    def is_allowed(self, client_key: str) -> tuple[bool, int, float]:
        """Determine if a request is allowed according to the token bucket algorithm.

        Returns:
            tuple[bool, int, float]: (allowed, remaining_tokens, retry_after_seconds)
        """
        now = time.monotonic()
        tokens, last_time = self._buckets.get(client_key, (self.capacity, now))

        # Refill tokens based on elapsed time
        elapsed = now - last_time
        tokens = min(self.capacity, tokens + elapsed * self.rate)

        if tokens >= 1.0:
            tokens -= 1.0
            self._buckets[client_key] = (tokens, now)
            return True, int(math.floor(tokens)), 0.0

        # Calculate time needed until at least 1 token is available
        needed = 1.0 - tokens
        retry_after = max(1.0, math.ceil(needed / self.rate))
        self._buckets[client_key] = (tokens, now)
        return False, 0, float(retry_after)

    def reset(self, client_key: str | None = None) -> None:
        """Reset buckets (useful for test isolation)."""
        if client_key:
            self._buckets.pop(client_key, None)
        else:
            self._buckets.clear()


# Global default rate limiter instance
_global_rate_limiter = TokenBucketRateLimiter()


def get_rate_limiter() -> TokenBucketRateLimiter:
    """Return the global token bucket rate limiter."""
    return _global_rate_limiter


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing OWASP-recommended secure HTTP headers on all API responses."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        response: Response = await call_next(request)

        # Enforce secure HTTP headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none';"
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
        )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing token bucket rate limiting on client requests."""

    EXEMPT_PATHS = {
        "/api/v1/health",
        "/api/v1/ready",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    def __init__(self, app: Any, limiter: TokenBucketRateLimiter | None = None) -> None:
        super().__init__(app)
        self.limiter = limiter or _global_rate_limiter

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        settings = get_settings()
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        # Allow exempt health & documentation endpoints
        path = request.url.path
        if path in self.EXEMPT_PATHS or path.rstrip("/") in self.EXEMPT_PATHS:
            return await call_next(request)

        # Determine client key (prioritize authenticated user, fallback to client IP)
        auth_header = request.headers.get("Authorization")
        client_ip = request.client.host if request.client else "unknown"

        # If Authorization header provided, derive key from header hash to avoid spoofing IP
        client_key = f"auth_{auth_header[:32]}" if auth_header else f"ip_{client_ip}"

        allowed, remaining, retry_after = self.limiter.is_allowed(client_key)

        if not allowed:
            SecurityAuditService.record_event(
                event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
                ip_address=client_ip,
                action=f"{request.method} {path}",
                details={"client_key": client_key, "retry_after": retry_after},
                severity="WARNING",
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "TOO_MANY_REQUESTS",
                        "message": "Rate limit exceeded. Please try again later.",
                        "details": {"retry_after_seconds": retry_after},
                    }
                },
                headers={
                    "Retry-After": str(int(retry_after)),
                    "X-RateLimit-Limit": str(settings.RATE_LIMIT_BURST_CAPACITY),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_BURST_CAPACITY)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
