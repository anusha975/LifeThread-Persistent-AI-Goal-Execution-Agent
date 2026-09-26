import logging
from collections.abc import Callable, Coroutine
from typing import Any

from pydantic import BaseModel

from lifethread_agent.tools.base import (
    RetryPolicy,
    ToolDefinition,
    ToolPermissionLevel,
)

logger = logging.getLogger("lifethread.agent.tools.registry")


class ToolRegistry:
    """Registry maintaining catalog of registered tool definitions and metadata."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a ToolDefinition into the catalog."""
        if tool.name in self._tools:
            logger.warning(f"Overwriting previously registered tool [{tool.name}] in registry.")
        self._tools[tool.name] = tool
        logger.info(
            f"Registered tool [{tool.name}] (permission: {tool.permission_level.name}, timeout: {tool.timeout}s)"
        )

    def tool(
        self,
        name: str,
        description: str,
        input_schema: type[BaseModel],
        output_schema: type[BaseModel] | None = None,
        permission_level: ToolPermissionLevel = ToolPermissionLevel.STANDARD,
        timeout: float = 30.0,
        retry_policy: RetryPolicy | None = None,
    ) -> Callable[
        [Callable[..., Coroutine[Any, Any, Any]]],
        Callable[..., Coroutine[Any, Any, Any]],
    ]:
        """Decorator to declare and register an async function as a tool."""

        def decorator(
            func: Callable[..., Coroutine[Any, Any, Any]],
        ) -> Callable[..., Coroutine[Any, Any, Any]]:
            tool_def = ToolDefinition(
                name=name,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                permission_level=permission_level,
                timeout=timeout,
                retry_policy=retry_policy or RetryPolicy(),
                handler=func,
            )
            self.register(tool_def)
            return func

        return decorator

    def get(self, name: str) -> ToolDefinition | None:
        """Retrieve tool definition by name."""
        return self._tools.get(name)

    def list_tools(
        self, max_permission_level: ToolPermissionLevel | None = None
    ) -> list[ToolDefinition]:
        """List all tools, optionally filtering out tools requiring higher permissions than max_permission_level."""
        if max_permission_level is None:
            return list(self._tools.values())
        return [
            tool for tool in self._tools.values() if tool.permission_level <= max_permission_level
        ]

    def list_tool_names(self, max_permission_level: ToolPermissionLevel | None = None) -> list[str]:
        """List names of registered tools."""
        return [tool.name for tool in self.list_tools(max_permission_level)]

    def get_schemas(self) -> list[dict[str, Any]]:
        """Export tool specifications into standard JSON schemas for LLM tool invocation."""
        schemas: list[dict[str, Any]] = []
        for tool in self._tools.values():
            if isinstance(tool.input_schema, type) and issubclass(tool.input_schema, BaseModel):
                parameters = tool.input_schema.model_json_schema()
            elif isinstance(tool.input_schema, dict):
                parameters = tool.input_schema
            else:
                parameters = {"type": "object", "properties": {}}

            schema = {
                "name": tool.name,
                "description": tool.description,
                "parameters": parameters,
                "permission_level": tool.permission_level.name,
                "timeout": tool.timeout,
            }
            schemas.append(schema)
        return schemas

    def unregister(self, name: str) -> bool:
        """Remove a tool from the registry."""
        if name in self._tools:
            del self._tools[name]
            logger.info(f"Unregistered tool [{name}]")
            return True
        return False
