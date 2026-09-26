import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from lifethread_agent.tools import (
    ToolCall,
    ToolErrorCode,
    ToolExecutor,
    ToolPermissionLevel,
    ToolRegistry,
)

from mcp_server.schemas import (
    JSONRPCErrorCode,
    JSONRPCRequest,
    JSONRPCResponse,
    MCPContentItem,
    MCPToolCallResult,
)

logger = logging.getLogger("lifethread.mcp.transport")


class MCPDispatcher:
    """Dispatches incoming JSON-RPC 2.0 requests to tool catalog and executor."""

    def __init__(self, registry: ToolRegistry, executor: ToolExecutor) -> None:
        self.registry = registry
        self.executor = executor

    async def dispatch(
        self, req: JSONRPCRequest, context: dict[str, Any] | None = None
    ) -> JSONRPCResponse:
        """Route JSON-RPC request to appropriate MCP handler."""
        method = req.method
        ctx = context or {}

        try:
            if method == "initialize":
                return await self._handle_initialize(req)
            elif method == "tools/list":
                return await self._handle_tools_list(req)
            elif method == "tools/call":
                return await self._handle_tools_call(req, ctx)
            elif method == "ping":
                return JSONRPCResponse.success(id=req.id, result={"status": "pong"})
            else:
                logger.warning(f"Unrecognized JSON-RPC method: {method}")
                return JSONRPCResponse.failure(
                    id=req.id,
                    code=JSONRPCErrorCode.METHOD_NOT_FOUND,
                    message=f"Method '{method}' not found.",
                )
        except Exception as exc:
            logger.exception(f"Internal error dispatching method [{method}]: {exc}")
            return JSONRPCResponse.failure(
                id=req.id,
                code=JSONRPCErrorCode.INTERNAL_ERROR,
                message=f"Internal MCP server error: {exc}",
            )

    async def _handle_initialize(self, req: JSONRPCRequest) -> JSONRPCResponse:
        """Handle MCP protocol initialization."""
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {},
                "prompts": {},
            },
            "serverInfo": {
                "name": "LifeThread MCP Server",
                "version": "0.1.0",
            },
        }
        return JSONRPCResponse.success(id=req.id, result=result)

    async def _handle_tools_list(self, req: JSONRPCRequest) -> JSONRPCResponse:
        """Handle MCP tools/list discovery."""
        schemas = self.registry.get_schemas()
        mcp_tools = []
        for s in schemas:
            mcp_tools.append(
                {
                    "name": s["name"],
                    "description": s["description"],
                    "inputSchema": s.get("parameters", {}),
                }
            )
        return JSONRPCResponse.success(id=req.id, result={"tools": mcp_tools})

    async def _handle_tools_call(
        self, req: JSONRPCRequest, context: dict[str, Any]
    ) -> JSONRPCResponse:
        """Handle MCP tools/call tool execution with validation and result shaping."""
        params = req.params or {}
        tool_name = params.get("name") or params.get("tool_name")
        arguments = params.get("arguments") or params.get("args") or {}

        if not tool_name:
            return JSONRPCResponse.failure(
                id=req.id,
                code=JSONRPCErrorCode.INVALID_PARAMS,
                message="Missing required parameter 'name' for tools/call.",
            )

        tool_call = ToolCall(
            tool_name=tool_name,
            arguments=arguments,
            caller_permission_level=ToolPermissionLevel.ADMIN,  # MCP server proxies caller
            context=context,
        )

        tool_result = await self.executor.execute(tool_call)

        if not tool_result.success and tool_result.error:
            err_code = tool_result.error.get("code")
            err_msg = tool_result.error.get("message", "Tool execution failed")
            err_details = tool_result.error.get("details")

            # Route input/param validation failures to standard JSON-RPC -32602
            if err_code == ToolErrorCode.VALIDATION_ERROR.value:
                return JSONRPCResponse.failure(
                    id=req.id,
                    code=JSONRPCErrorCode.INVALID_PARAMS,
                    message=err_msg,
                    data=err_details,
                )
            elif err_code == ToolErrorCode.TOOL_NOT_FOUND.value:
                return JSONRPCResponse.failure(
                    id=req.id,
                    code=JSONRPCErrorCode.METHOD_NOT_FOUND,
                    message=err_msg,
                    data=err_details,
                )
            else:
                # Execution error inside tool handler: format as standard MCP tool failure block
                mcp_res = MCPToolCallResult(
                    content=[MCPContentItem(type="text", text=err_msg)],
                    isError=True,
                )
                return JSONRPCResponse.success(id=req.id, result=mcp_res.model_dump())

        # Successful tool outcome
        serialized_data = (
            json.dumps(tool_result.data, default=str)
            if not isinstance(tool_result.data, str)
            else tool_result.data
        )

        mcp_res = MCPToolCallResult(
            content=[MCPContentItem(type="text", text=serialized_data)],
            isError=False,
        )
        return JSONRPCResponse.success(id=req.id, result=mcp_res.model_dump())


def format_sse_event(event_type: str, data: Any) -> str:
    """Format SSE payload according to W3C EventSource specifications."""
    payload_str = json.dumps(data, default=str) if not isinstance(data, str) else data
    return f"event: {event_type}\ndata: {payload_str}\n\n"


async def stream_tool_execution(
    req: JSONRPCRequest,
    dispatcher: MCPDispatcher,
    context: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Streamable HTTP SSE generator: sends progress events before final result."""
    tool_name = (req.params or {}).get("name", "tool")

    # Initial start event
    yield format_sse_event(
        "progress",
        {"status": "executing", "method": req.method, "tool": tool_name},
    )

    # Dispatch request
    response = await dispatcher.dispatch(req, context)

    # Terminal message event
    yield format_sse_event("message", response.model_dump())
