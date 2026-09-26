from datetime import UTC, datetime
from typing import Any, Literal

from lifethread_agent.tools import (
    ToolExecutor,
    ToolPermissionLevel,
    ToolRegistry,
)
from pydantic import BaseModel, Field

# ============================================================================
# SAFE TEST TOOL SCHEMAS
# ============================================================================


class PingInput(BaseModel):
    message: str = Field(default="ping", description="Ping message string")


class PingOutput(BaseModel):
    reply: str
    server_time: str


class EchoInput(BaseModel):
    text: str = Field(..., min_length=1, description="Text string to echo back")
    repeat: int = Field(default=1, ge=1, le=10, description="Repetition count")


class EchoOutput(BaseModel):
    echoed: str


class CalculateInput(BaseModel):
    a: float = Field(..., description="First operand")
    b: float = Field(..., description="Second operand")
    operation: Literal["add", "subtract", "multiply", "divide"] = Field(
        ..., description="Arithmetic operator to execute"
    )


class CalculateOutput(BaseModel):
    result: float
    operation: str


# ============================================================================
# FACTORY FOR DEFAULT MCP TOOL REGISTRY
# ============================================================================


def create_safe_mcp_tool_registry() -> ToolRegistry:
    """Instantiate and register safe foundational test tools for MCP exposure."""
    registry = ToolRegistry()

    @registry.tool(
        name="ping",
        description="Verify server connectivity and fetch current server UTC timestamp",
        input_schema=PingInput,
        output_schema=PingOutput,
        permission_level=ToolPermissionLevel.READ_ONLY,
    )
    async def ping(message: str = "ping") -> dict[str, Any]:
        return {
            "reply": "pong",
            "server_time": datetime.now(UTC).isoformat(),
        }

    @registry.tool(
        name="echo",
        description="Echo back supplied text string with optional repetitions",
        input_schema=EchoInput,
        output_schema=EchoOutput,
        permission_level=ToolPermissionLevel.READ_ONLY,
    )
    async def echo(text: str, repeat: int = 1) -> dict[str, Any]:
        return {
            "echoed": " ".join([text] * repeat),
        }

    @registry.tool(
        name="calculate",
        description="Safely perform standard arithmetic calculations",
        input_schema=CalculateInput,
        output_schema=CalculateOutput,
        permission_level=ToolPermissionLevel.READ_ONLY,
    )
    async def calculate(a: float, b: float, operation: str) -> dict[str, Any]:
        if operation == "add":
            res = a + b
        elif operation == "subtract":
            res = a - b
        elif operation == "multiply":
            res = a * b
        elif operation == "divide":
            if b == 0:
                raise ValueError("Division by zero is undefined.")
            res = a / b
        else:
            raise ValueError(f"Unsupported operation: {operation}")

        return {"result": float(res), "operation": operation}

    # Register Goal Engine tools (Module 11)
    from mcp_server.tools_goals import register_goal_mcp_tools

    register_goal_mcp_tools(registry)

    # Register Planning Engine tools (Module 12)
    from mcp_server.tools_planning import register_planning_mcp_tools

    register_planning_mcp_tools(registry)

    # Register Memory tools (Module 13)
    from mcp_server.tools_memory import register_memory_mcp_tools

    register_memory_mcp_tools(registry)

    # Register Evaluation tools (Module 14)
    from mcp_server.tools_evaluation import register_evaluation_mcp_tools

    register_evaluation_mcp_tools(registry)

    return registry


_DEFAULT_REGISTRY: ToolRegistry | None = None
_DEFAULT_EXECUTOR: ToolExecutor | None = None


def get_default_mcp_registry() -> ToolRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = create_safe_mcp_tool_registry()
    return _DEFAULT_REGISTRY


def get_default_mcp_executor() -> ToolExecutor:
    global _DEFAULT_EXECUTOR
    if _DEFAULT_EXECUTOR is None:
        _DEFAULT_EXECUTOR = ToolExecutor(get_default_mcp_registry())
    return _DEFAULT_EXECUTOR
