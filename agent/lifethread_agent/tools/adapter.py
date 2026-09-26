from typing import Any

from lifethread_agent.models import ToolExecutionResult
from lifethread_agent.ports import ToolExecutionPort
from lifethread_agent.state_machine import CancellationToken
from lifethread_agent.tools.base import ToolCall, ToolPermissionLevel
from lifethread_agent.tools.executor import ToolExecutor
from lifethread_agent.tools.registry import ToolRegistry


class GenericToolExecutionAdapter(ToolExecutionPort):
    """Adapts the Generic Tool Execution Framework (ToolExecutor) to the Agent Orchestrator's ToolExecutionPort."""

    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor | None = None,
        default_caller_permission: ToolPermissionLevel = ToolPermissionLevel.STANDARD,
    ) -> None:
        self.registry = registry
        self.executor = executor or ToolExecutor(registry)
        self.default_caller_permission = default_caller_permission

    async def get_available_tools(self) -> list[str]:
        """Return list of tool names currently available to the agent."""
        return self.registry.list_tool_names(max_permission_level=self.default_caller_permission)

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> ToolExecutionResult:
        """Execute a tool through ToolExecutor and convert result into domain ToolExecutionResult."""
        tool_call = ToolCall(
            tool_name=tool_name,
            arguments=arguments,
            caller_permission_level=self.default_caller_permission,
            context=context,
        )

        cancellation_token = context.get("cancellation_token")
        if cancellation_token and not isinstance(cancellation_token, CancellationToken):
            cancellation_token = None

        tool_result = await self.executor.execute(
            tool_call=tool_call,
            cancellation_token=cancellation_token,
        )

        error_msg = None
        if not tool_result.success and tool_result.error:
            error_msg = tool_result.error.get("message", "Tool execution failed")

        return ToolExecutionResult(
            tool_name=tool_name,
            success=tool_result.success,
            result=tool_result.data,
            error=error_msg,
            execution_time_ms=tool_result.execution_time_ms,
        )
