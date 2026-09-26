import asyncio
import inspect
import logging
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from lifethread_agent.state_machine import CancellationToken
from lifethread_agent.tools.base import (
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolErrorCode,
    ToolResult,
)
from lifethread_agent.tools.registry import ToolRegistry

logger = logging.getLogger("lifethread.agent.tools.executor")


class ToolExecutor:
    """Safe, auditable executor for registered agent tools.

    Enforces input schema validation, output schema validation, permission checks,
    per-tool timeouts, automatic retries with exponential backoff, and execution metrics.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(
        self,
        tool_call: ToolCall,
        cancellation_token: CancellationToken | None = None,
    ) -> ToolResult:
        """Execute a tool call against the registry with full validation and safeguards."""
        start_time = time.perf_counter()
        token = cancellation_token or CancellationToken()

        # 1. Tool discovery
        tool = self.registry.get(tool_call.tool_name)
        if not tool:
            err = ToolError(
                code=ToolErrorCode.TOOL_NOT_FOUND,
                message=f"Tool '{tool_call.tool_name}' is not registered in the tool catalog.",
            )
            return self._build_result(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                success=False,
                error=err,
                start_time=start_time,
            )

        # 2. Permission checking
        if tool_call.caller_permission_level < tool.permission_level:
            try:
                from app.core.audit import SecurityAuditService, SecurityEventType
                SecurityAuditService.record_event(
                    event_type=SecurityEventType.TOOL_PERMISSION_DENIED,
                    resource_type="tool",
                    resource_id=tool.name,
                    action="INVOKE_TOOL",
                    details={
                        "caller_level": tool_call.caller_permission_level.name,
                        "required_level": tool.permission_level.name,
                    },
                    severity="WARNING",
                )
            except Exception:
                pass

            err = ToolError(
                code=ToolErrorCode.PERMISSION_DENIED,
                message=(
                    f"Caller permission level [{tool_call.caller_permission_level.name}] is insufficient "
                    f"to invoke tool '{tool.name}' requiring [{tool.permission_level.name}]."
                ),
                details={
                    "required_level": tool.permission_level.name,
                    "caller_level": tool_call.caller_permission_level.name,
                },
            )
            return self._build_result(
                call_id=tool_call.call_id,
                tool_name=tool.name,
                success=False,
                error=err,
                start_time=start_time,
            )

        # 2b. Malicious argument defense
        try:
            from app.core.tool_security import MaliciousArgumentDetector
            is_safe, error_msg = MaliciousArgumentDetector.validate_tool_arguments(
                tool_name=tool.name,
                arguments=tool_call.arguments,
                user_id=str(tool_call.context.get("user_id")) if tool_call.context else None,
                record_audit=True,
            )
            if not is_safe:
                err = ToolError(
                    code=ToolErrorCode.MALICIOUS_ARGUMENTS,
                    message=error_msg or f"Malicious arguments detected in call to '{tool.name}'.",
                    details={"arguments": str(tool_call.arguments)[:200]},
                )
                return self._build_result(
                    call_id=tool_call.call_id,
                    tool_name=tool.name,
                    success=False,
                    error=err,
                    start_time=start_time,
                )
        except ImportError:
            pass

        # 3. Cancellation check before execution
        if token.is_cancelled:
            err = ToolError(
                code=ToolErrorCode.CANCELLED,
                message=f"Tool call cancelled before start: {token.reason}",
            )
            return self._build_result(
                call_id=tool_call.call_id,
                tool_name=tool.name,
                success=False,
                error=err,
                start_time=start_time,
            )

        # 4. Input validation
        validated_input: Any = tool_call.arguments
        if isinstance(tool.input_schema, type) and issubclass(tool.input_schema, BaseModel):
            try:
                validated_input = tool.input_schema.model_validate(tool_call.arguments)
            except ValidationError as ve:
                err = ToolError(
                    code=ToolErrorCode.VALIDATION_ERROR,
                    message=f"Input validation failed for tool '{tool.name}': {ve.errors()}",
                    details={"validation_errors": self._clean_validation_errors(ve.errors())},
                )
                return self._build_result(
                    call_id=tool_call.call_id,
                    tool_name=tool.name,
                    success=False,
                    error=err,
                    start_time=start_time,
                )

        # 5. Execution with timeout & retry handling
        raw_result, error, retries_attempted = await self._execute_with_retries(
            tool=tool,
            validated_input=validated_input,
            context=tool_call.context,
            token=token,
        )

        if error:
            return self._build_result(
                call_id=tool_call.call_id,
                tool_name=tool.name,
                success=False,
                error=error,
                start_time=start_time,
                retries_attempted=retries_attempted,
            )

        # 6. Output validation
        final_data = raw_result
        if (
            tool.output_schema
            and isinstance(tool.output_schema, type)
            and issubclass(tool.output_schema, BaseModel)
        ):
            try:
                if isinstance(raw_result, dict):
                    final_data = tool.output_schema.model_validate(raw_result).model_dump(
                        mode="json"
                    )
                elif isinstance(raw_result, tool.output_schema):
                    final_data = raw_result.model_dump(mode="json")
                else:
                    final_data = tool.output_schema.model_validate(raw_result).model_dump(
                        mode="json"
                    )
            except ValidationError as ve:
                err = ToolError(
                    code=ToolErrorCode.VALIDATION_ERROR,
                    message=f"Output validation failed for tool '{tool.name}': {ve.errors()}",
                    details={"validation_errors": self._clean_validation_errors(ve.errors())},
                )
                return self._build_result(
                    call_id=tool_call.call_id,
                    tool_name=tool.name,
                    success=False,
                    error=err,
                    start_time=start_time,
                    retries_attempted=retries_attempted,
                )

        return self._build_result(
            call_id=tool_call.call_id,
            tool_name=tool.name,
            success=True,
            data=final_data,
            start_time=start_time,
            retries_attempted=retries_attempted,
        )

    async def _execute_with_retries(
        self,
        tool: ToolDefinition,
        validated_input: Any,
        context: dict[str, Any],
        token: CancellationToken,
    ) -> tuple[Any, ToolError | None, int]:
        """Execute tool handler with timeout and exponential backoff retry loop."""
        if tool.handler is None:
            return (
                None,
                ToolError(
                    code=ToolErrorCode.EXECUTION_FAILED,
                    message=f"Tool '{tool.name}' has no executable handler registered.",
                ),
                0,
            )

        policy = tool.retry_policy
        max_attempts = 1 + policy.max_retries
        delay = policy.initial_delay_seconds
        retries_attempted = 0

        for attempt in range(1, max_attempts + 1):
            if token.is_cancelled:
                return (
                    None,
                    ToolError(
                        code=ToolErrorCode.CANCELLED,
                        message=f"Tool execution cancelled: {token.reason}",
                    ),
                    retries_attempted,
                )

            try:
                # Per-execution timeout
                async with asyncio.timeout(tool.timeout):
                    result = await self._invoke_handler(tool.handler, validated_input, context)
                return result, None, retries_attempted

            except TimeoutError:
                if attempt < max_attempts and "TimeoutError" in policy.retryable_error_types:
                    retries_attempted += 1
                    logger.warning(
                        f"Tool '{tool.name}' timed out (attempt {attempt}/{max_attempts}). "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    delay *= policy.backoff_factor
                else:
                    return (
                        None,
                        ToolError(
                            code=ToolErrorCode.TIMEOUT_ERROR,
                            message=f"Tool '{tool.name}' timed out after {tool.timeout}s (attempts: {attempt}).",
                            details={"timeout_seconds": tool.timeout},
                            recoverable=False,
                        ),
                        retries_attempted,
                    )

            except Exception as exc:
                exc_type_name = type(exc).__name__
                is_retryable = exc_type_name in policy.retryable_error_types

                if attempt < max_attempts and is_retryable:
                    retries_attempted += 1
                    logger.warning(
                        f"Tool '{tool.name}' failed with {exc_type_name} (attempt {attempt}/{max_attempts}). "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    delay *= policy.backoff_factor
                else:
                    logger.error(f"Tool '{tool.name}' execution failed: {exc}", exc_info=True)
                    return (
                        None,
                        ToolError(
                            code=ToolErrorCode.EXECUTION_FAILED,
                            message=f"Tool '{tool.name}' failed: {exc}",
                            details={"exception_type": exc_type_name},
                            recoverable=is_retryable,
                        ),
                        retries_attempted,
                    )

        return (
            None,
            ToolError(
                code=ToolErrorCode.EXECUTION_FAILED,
                message=f"Tool '{tool.name}' exhausted all {max_attempts} attempts.",
            ),
            retries_attempted,
        )

    async def _invoke_handler(
        self,
        handler: Any,
        validated_input: Any,
        context: dict[str, Any],
    ) -> Any:
        """Call async tool handler, inspecting its signature to bind parameters cleanly."""
        sig = inspect.signature(handler)
        params = sig.parameters

        # If handler takes single input model parameter
        if len(params) == 1 and isinstance(validated_input, BaseModel):
            return await handler(validated_input)

        # If handler takes input + context
        if len(params) == 2 and isinstance(validated_input, BaseModel) and "context" in params:
            return await handler(validated_input, context=context)

        # If handler takes kwargs
        if isinstance(validated_input, BaseModel):
            kwargs = validated_input.model_dump()
        elif isinstance(validated_input, dict):
            kwargs = dict(validated_input)
        else:
            kwargs = {}

        if "context" in params:
            kwargs["context"] = context

        return await handler(**kwargs)

    def _build_result(
        self,
        call_id: str,
        tool_name: str,
        success: bool,
        start_time: float,
        data: Any = None,
        error: ToolError | None = None,
        retries_attempted: int = 0,
    ) -> ToolResult:
        """Helper to construct normalized ToolResult."""
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            success=success,
            data=data,
            error=error.to_dict() if error else None,
            execution_time_ms=elapsed_ms,
            retries_attempted=retries_attempted,
            executed_at=datetime.now(UTC),
        )

    @staticmethod
    def _clean_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ensure all validation error dictionaries are strictly JSON-serializable."""
        clean = []
        for e in errors:
            item = {k: v for k, v in e.items() if k != "ctx"}
            if "ctx" in e and isinstance(e["ctx"], dict):
                item["ctx"] = {ck: str(cv) for ck, cv in e["ctx"].items()}
            clean.append(item)
        return clean
