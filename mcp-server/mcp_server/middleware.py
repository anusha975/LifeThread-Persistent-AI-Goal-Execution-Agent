import logging
import secrets
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from mcp_server.config import get_mcp_settings

logger = logging.getLogger("lifethread.mcp.middleware")


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Middleware attaching a unique X-Request-ID correlation header to requests and responses."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        req_id = request.headers.get("X-Request-ID") or f"mcp_{uuid.uuid4().hex[:12]}"
        request.state.request_id = req_id

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing API Key authentication on protected MCP endpoints."""

    UNAUTHENTICATED_PATHS = {
        "/health",
        "/info",
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        settings = get_mcp_settings()

        # If authentication disabled, allow all requests
        if not settings.MCP_AUTH_ENABLED:
            return await call_next(request)

        # Allow unauthenticated health and meta endpoints
        if request.url.path in self.UNAUTHENTICATED_PATHS:
            return await call_next(request)

        # Extract token from Authorization: Bearer <key> or X-API-Key: <key>
        auth_header = request.headers.get("Authorization")
        api_key_header = request.headers.get("X-API-Key")

        provided_key = None
        if auth_header and auth_header.startswith("Bearer "):
            provided_key = auth_header.split("Bearer ", 1)[1].strip()
        elif api_key_header:
            provided_key = api_key_header.strip()

        if not provided_key or not secrets.compare_digest(provided_key, settings.MCP_API_KEY):
            logger.warning(
                f"Unauthorized request to [{request.url.path}] (request_id: {getattr(request.state, 'request_id', 'unknown')})"
            )
            try:
                from app.core.audit import SecurityAuditService, SecurityEventType

                client_ip = request.client.host if request.client else "unknown"
                SecurityAuditService.record_event(
                    event_type=SecurityEventType.MCP_AUTH_FAILURE,
                    ip_address=client_ip,
                    action=f"MCP_{request.method}_{request.url.path}",
                    details={
                        "path": request.url.path,
                        "has_bearer": bool(auth_header),
                        "has_api_key_header": bool(api_key_header),
                    },
                    severity="WARNING",
                )
            except Exception:
                pass
            return JSONResponse(
                status_code=401,
                content={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32001,
                        "message": "Unauthorized: Invalid or missing MCP API key.",
                    },
                },
                headers={
                    "X-Request-ID": getattr(request.state, "request_id", ""),
                },
            )

        return await call_next(request)
