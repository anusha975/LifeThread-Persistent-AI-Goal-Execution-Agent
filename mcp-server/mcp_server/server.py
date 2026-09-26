import logging
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from mcp_server.config import get_mcp_settings
from mcp_server.middleware import (
    AuthenticationMiddleware,
    RequestTracingMiddleware,
)
from mcp_server.schemas import JSONRPCRequest, JSONRPCResponse
from mcp_server.tools import (
    get_default_mcp_executor,
    get_default_mcp_registry,
)
from mcp_server.transport import (
    MCPDispatcher,
    format_sse_event,
    stream_tool_execution,
)

logger = logging.getLogger("lifethread.mcp")


class MCPHealthResponse(BaseModel):
    status: str
    server_name: str
    transport: str
    tools_count: int
    version: str
    timestamp: str


class MCPInfoResponse(BaseModel):
    server: str
    protocol_version: str
    capabilities: dict[str, Any]


def create_mcp_app() -> FastAPI:
    """Factory creating the MCP standalone application with Streamable HTTP and Auth."""
    settings = get_mcp_settings()
    app = FastAPI(
        title=settings.MCP_SERVER_NAME,
        version="0.1.0",
        description="LifeThread Model Context Protocol (MCP) Service",
    )

    # Attach middlewares (outer: tracing, inner: auth)
    app.add_middleware(AuthenticationMiddleware)
    app.add_middleware(RequestTracingMiddleware)

    registry = get_default_mcp_registry()
    executor = get_default_mcp_executor()
    dispatcher = MCPDispatcher(registry=registry, executor=executor)

    @app.get(
        "/health",
        response_model=MCPHealthResponse,
        status_code=status.HTTP_200_OK,
    )
    async def health() -> MCPHealthResponse:
        return MCPHealthResponse(
            status="healthy",
            server_name=settings.MCP_SERVER_NAME,
            transport=settings.MCP_TRANSPORT,
            tools_count=len(registry.list_tools()),
            version="0.1.0",
            timestamp=datetime.now(UTC).isoformat(),
        )

    @app.get("/info", response_model=MCPInfoResponse)
    async def info() -> MCPInfoResponse:
        return MCPInfoResponse(
            server=settings.MCP_SERVER_NAME,
            protocol_version="2024-11-05",
            capabilities={
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
                "streamable_http": True,
            },
        )

    @app.post("/mcp", response_model=JSONRPCResponse)
    async def mcp_endpoint(request: Request, body: JSONRPCRequest) -> Any:
        """Primary MCP JSON-RPC 2.0 endpoint supporting standard JSON and Streamable HTTP (SSE)."""
        accept_header = request.headers.get("accept", "")
        req_id = getattr(request.state, "request_id", "")
        context = {
            "request_id": req_id,
            "caller_ip": request.client.host if request.client else "unknown",
        }

        # Check if caller requested streamable HTTP (text/event-stream)
        if "text/event-stream" in accept_header:
            return StreamingResponse(
                stream_tool_execution(req=body, dispatcher=dispatcher, context=context),
                media_type="text/event-stream",
                headers={"X-Request-ID": req_id},
            )

        # Standard JSON-RPC response
        response = await dispatcher.dispatch(req=body, context=context)
        return JSONResponse(
            status_code=200,
            content=response.model_dump(mode="json"),
            headers={"X-Request-ID": req_id},
        )

    @app.get("/sse")
    async def sse_endpoint(request: Request) -> StreamingResponse:
        """Standard MCP Server-Sent Events initial connection endpoint."""
        req_id = getattr(request.state, "request_id", "")

        async def sse_generator():
            # Initial event pointing client to the message delivery endpoint
            yield format_sse_event("endpoint", "/mcp?session_id=" + req_id)
            # Connectivity ping event
            yield format_sse_event("ping", {"timestamp": datetime.now(UTC).isoformat()})

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={"X-Request-ID": req_id},
        )

    return app


app = create_mcp_app()


def main() -> None:
    """CLI entrypoint for standalone MCP server execution."""
    settings = get_mcp_settings()
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    logger.info(
        f"Starting MCP server on {settings.MCP_SERVER_HOST}:{settings.MCP_SERVER_PORT} "
        f"(transport: {settings.MCP_TRANSPORT})"
    )
    uvicorn.run(
        app,
        host=settings.MCP_SERVER_HOST,
        port=settings.MCP_SERVER_PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
