import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("lifethread.http")


class TimingMiddleware(BaseHTTPMiddleware):
    """Middleware measuring request duration and emitting structured completion logs."""

    HEADER_NAME = "X-Process-Time-Ms"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.perf_counter()
        request_id = getattr(request.state, "request_id", None) or request.headers.get(
            "X-Request-ID"
        )

        logger.debug(
            f"--> {request.method} {request.url.path}",
            extra={"method": request.method, "path": request.url.path, "request_id": request_id},
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"<-- {request.method} {request.url.path} FAILED after {duration_ms:.2f}ms",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                    "request_id": request_id,
                },
            )
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000
        response.headers[self.HEADER_NAME] = f"{duration_ms:.2f}"

        client_ip = request.client.host if request.client else None
        logger.info(
            f"<-- {request.method} {request.url.path} {response.status_code} in {duration_ms:.2f}ms",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client_ip": client_ip,
                "request_id": request_id,
            },
        )

        return response
