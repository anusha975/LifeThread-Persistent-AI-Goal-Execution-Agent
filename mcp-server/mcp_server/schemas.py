from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field


class JSONRPCErrorCode(IntEnum):
    """Standard JSON-RPC 2.0 and MCP error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    UNAUTHORIZED = -32001


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 error representation."""

    code: int = Field(..., description="Error code number")
    message: str = Field(..., description="Human-readable error explanation")
    data: Any = Field(default=None, description="Detailed diagnostic or validation payload")


class JSONRPCRequest(BaseModel):
    """Incoming JSON-RPC 2.0 request payload."""

    jsonrpc: str = Field(default="2.0", description="Protocol version identifier")
    id: str | int | None = Field(default=None, description="Client-assigned correlation identifier")
    method: str = Field(..., description="Target RPC method name, e.g. 'tools/list', 'tools/call'")
    params: dict[str, Any] = Field(
        default_factory=dict, description="Method-specific parameter payload"
    )


class JSONRPCResponse(BaseModel):
    """Outgoing JSON-RPC 2.0 response payload."""

    jsonrpc: str = Field(default="2.0", description="Protocol version identifier")
    id: str | int | None = Field(default=None, description="Correlated request identifier")
    result: Any = Field(default=None, description="Method execution result payload")
    error: JSONRPCError | None = Field(default=None, description="Error payload if method failed")

    @classmethod
    def success(cls, id: str | int | None, result: Any) -> "JSONRPCResponse":
        return cls(id=id, result=result, error=None)

    @classmethod
    def failure(
        cls,
        id: str | int | None,
        code: int | JSONRPCErrorCode,
        message: str,
        data: Any = None,
    ) -> "JSONRPCResponse":
        int_code = code.value if isinstance(code, JSONRPCErrorCode) else code
        return cls(
            id=id, result=None, error=JSONRPCError(code=int_code, message=message, data=data)
        )


class MCPContentItem(BaseModel):
    """Content item inside an MCP tool call outcome."""

    type: str = Field(default="text", description="MIME or item type (e.g. 'text')")
    text: str = Field(..., description="Content payload string")


class MCPToolCallResult(BaseModel):
    """MCP standard tool execution result structure."""

    content: list[MCPContentItem] = Field(
        default_factory=list, description="Sequence of generated content blocks"
    )
    isError: bool = Field(default=False, description="Flag indicating if the tool yielded an error")
