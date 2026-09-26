import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_ctx


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware ensuring every request has a unique request ID.

    Extracts 'X-Request-ID' from incoming headers or generates a new UUID4.
    Binds the ID to request.state, response headers, and the async contextvar.
    """

    HEADER_NAME = "X-Request-ID"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming_id = request.headers.get(self.HEADER_NAME)
        request_id = incoming_id.strip() if incoming_id else uuid.uuid4().hex

        # Attach to request state
        request.state.request_id = request_id

        # Bind to async logging contextvar
        token = request_id_ctx.set(request_id)

        try:
            response = await call_next(request)
            response.headers[self.HEADER_NAME] = request_id
            return response
        finally:
            request_id_ctx.reset(token)
