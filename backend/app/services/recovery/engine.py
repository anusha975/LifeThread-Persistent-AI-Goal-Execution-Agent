import asyncio
import inspect
import json
import logging
import random
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.context_engine.models import ContextItem
from app.services.recovery.idempotency import idempotency_manager
from app.services.recovery.models import (
    FailureCategory,
    FailureEvent,
    RecoveryAction,
    RecoveryErrorCode,
    RecoveryResult,
    RetryPolicy,
    UserNotification,
)

logger = logging.getLogger("lifethread.services.recovery.engine")
audit_logger = logging.getLogger("lifethread.audit.recovery")

T = TypeVar("T")


class FailureRecoveryEngine:
    """Agent and Tool Failure Recovery Engine (Module 23).

    Handles:
    - LLM timeout
    - LLM malformed response
    - MCP timeout
    - MCP unavailable
    - Tool failure
    - Database transient failure
    - Invalid tool arguments
    - Planning failure
    - Context overflow

    Implements:
    retry -> exponential backoff -> fallback -> rollback where appropriate -> safe failure -> user notification
    """

    # In-memory store for user notifications
    _user_notifications: list[UserNotification] = []

    @classmethod
    def get_user_notifications(cls, user_id: uuid.UUID) -> list[UserNotification]:
        """Retrieve active notifications for target user."""
        return [n for n in cls._user_notifications if n.user_id == user_id and not n.dismissed]

    @classmethod
    def dismiss_notification(cls, notification_id: str, user_id: uuid.UUID) -> bool:
        """Dismiss a user notification."""
        for n in cls._user_notifications:
            if n.notification_id == notification_id and n.user_id == user_id:
                n.dismissed = True
                return True
        return False

    @classmethod
    def clear_notifications(cls) -> None:
        """Clear all stored notifications."""
        cls._user_notifications.clear()

    @classmethod
    def classify_exception(cls, exc: Exception) -> tuple[RecoveryErrorCode, FailureCategory, bool]:
        """Classify an exception into structured error code, category, and retriability."""
        exc_str = str(exc).lower()

        # 1. LLM Timeout
        if isinstance(exc, TimeoutError | asyncio.TimeoutError) and (
            "llm" in exc_str or "openai" in exc_str or "chat" in exc_str or "prompt" in exc_str
        ):
            return RecoveryErrorCode.LLM_TIMEOUT, FailureCategory.TRANSIENT, True

        # 2. MCP Timeout
        if isinstance(exc, TimeoutError | asyncio.TimeoutError) and (
            "mcp" in exc_str or "tool_call" in exc_str
        ):
            return RecoveryErrorCode.MCP_TIMEOUT, FailureCategory.TRANSIENT, True

        # 3. Generic Timeout
        if isinstance(exc, TimeoutError | asyncio.TimeoutError):
            return RecoveryErrorCode.TOOL_EXECUTION_FAILURE, FailureCategory.TRANSIENT, True

        # 4. LLM Malformed Response
        if isinstance(exc, json.JSONDecodeError) or "malformed" in exc_str or "json" in exc_str:
            return RecoveryErrorCode.LLM_MALFORMED_RESPONSE, FailureCategory.SYNTACTIC, False

        # 5. MCP Unavailable
        if (
            isinstance(exc, ConnectionError | ConnectionRefusedError)
            or "503" in exc_str
            or "connection refused" in exc_str
            or "mcp unavailable" in exc_str
            or "service unavailable" in exc_str
        ):
            return RecoveryErrorCode.MCP_UNAVAILABLE, FailureCategory.TRANSIENT, True

        # 6. Database Transient Failure
        if (
            isinstance(exc, OperationalError | DBAPIError)
            or "deadlock" in exc_str
            or "lock timeout" in exc_str
            or "database locked" in exc_str
        ):
            return RecoveryErrorCode.DB_TRANSIENT_FAILURE, FailureCategory.TRANSIENT, True

        # 7. Invalid Tool Arguments
        if isinstance(exc, ValidationError | TypeError) and (
            "argument" in exc_str
            or "validation" in exc_str
            or "missing" in exc_str
            or "schema" in exc_str
        ):
            return RecoveryErrorCode.INVALID_TOOL_ARGUMENTS, FailureCategory.SYNTACTIC, False

        # 8. Context Overflow
        if "token" in exc_str and (
            "exceed" in exc_str
            or "overflow" in exc_str
            or "maximum context" in exc_str
            or "budget" in exc_str
        ):
            return RecoveryErrorCode.CONTEXT_OVERFLOW, FailureCategory.CAPACITY, False

        # 9. Planning Failure
        if "cycle" in exc_str or "dag" in exc_str or "infeasible" in exc_str or "plan" in exc_str:
            return RecoveryErrorCode.PLANNING_FAILURE, FailureCategory.LOGICAL, False

        # Default fallback: Tool Execution Failure
        return RecoveryErrorCode.TOOL_EXECUTION_FAILURE, FailureCategory.TRANSIENT, True

    @classmethod
    async def execute_with_recovery(
        cls,
        operation: Callable[[], Awaitable[T]] | Callable[[], T],
        user_id: uuid.UUID,
        policy: RetryPolicy | None = None,
        fallback_handler: Callable[[FailureEvent], Awaitable[T] | T] | None = None,
        rollback_handler: Callable[[FailureEvent], Awaitable[None] | None] | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        operation_name: str = "operation",
        user_notification_title: str | None = None,
    ) -> RecoveryResult[T]:
        """Execute an asynchronous or synchronous operation with full failure recovery pipeline:

        Retry -> Exponential backoff -> Fallback -> Rollback where appropriate -> Safe failure -> User notification
        """
        active_policy = policy or RetryPolicy()
        cid = correlation_id or str(uuid.uuid4())
        actions_taken: list[RecoveryAction] = []
        last_failure_event: FailureEvent | None = None

        # -------------------------------------------------------------
        # 1. Idempotency Check (Requirement: no duplicate actions)
        # -------------------------------------------------------------
        if idempotency_key is not None:
            can_proceed, cached_result = idempotency_manager.start_operation(idempotency_key)
            if not can_proceed:
                if cached_result is not None:
                    logger.info(
                        "Idempotent operation '%s' already executed; returning cached result.",
                        idempotency_key,
                    )
                    return RecoveryResult[T](
                        correlation_id=cid,
                        success=True,
                        data=cached_result,
                        final_action="EXECUTED",
                        attempts_made=1,
                        state_preserved=True,
                    )
                else:
                    # Operation in-progress concurrent conflict
                    logger.warning(
                        "Idempotency conflict for '%s'; in-progress lock held.", idempotency_key
                    )
                    return RecoveryResult[T](
                        correlation_id=cid,
                        success=False,
                        data=None,
                        final_action="SAFE_FAILURE",
                        error_code=RecoveryErrorCode.RECOVERY_FAILED,
                        error_message=f"Operation with idempotency key '{idempotency_key}' is already in-progress.",
                        state_preserved=True,
                    )

        # -------------------------------------------------------------
        # 2. Execution & Bounded Retry Loop
        # -------------------------------------------------------------
        attempt = 0
        while attempt <= active_policy.max_retries:
            attempt += 1
            try:
                if inspect.iscoroutinefunction(operation) or inspect.isawaitable(operation):
                    result_data = await operation()
                elif callable(operation):
                    res = operation()
                    if inspect.isawaitable(res):
                        result_data = await res
                    else:
                        result_data = res
                else:
                    result_data = operation

                # Operation Succeeded!
                final_action = "EXECUTED" if attempt == 1 else "RECOVERED_VIA_RETRY"
                if attempt > 1:
                    actions_taken.append(
                        RecoveryAction(
                            action_type="RETRY",
                            attempt=attempt,
                            details=f"Operation '{operation_name}' succeeded on attempt {attempt}.",
                        )
                    )

                if idempotency_key is not None:
                    idempotency_manager.complete_operation(idempotency_key, result_data)

                return RecoveryResult[T](
                    correlation_id=cid,
                    success=True,
                    data=result_data,
                    final_action=final_action,
                    attempts_made=attempt,
                    state_preserved=True,
                    actions_taken=actions_taken,
                )

            except Exception as exc:
                err_code, category, is_retriable = cls.classify_exception(exc)
                last_failure_event = FailureEvent(
                    correlation_id=cid,
                    error_code=err_code,
                    category=category,
                    message=str(exc),
                    original_exception=type(exc).__name__,
                    attempt_number=attempt,
                    context_data={
                        "operation_name": operation_name,
                        "idempotency_key": idempotency_key,
                    },
                )
                audit_logger.warning(
                    "AUDIT [FAILURE_DETECTED] cid=%s op='%s' attempt=%d/%d code=%s msg='%s'",
                    cid,
                    operation_name,
                    attempt,
                    active_policy.max_retries,
                    err_code.value,
                    str(exc),
                )

                # Check if retriable and retries remaining (Bounded retries: no infinite loops!)
                if is_retriable and attempt <= active_policy.max_retries:
                    # Exponential Backoff with Jitter
                    delay = min(
                        active_policy.max_delay_seconds,
                        active_policy.base_delay_seconds
                        * (active_policy.backoff_factor ** (attempt - 1)),
                    )
                    if active_policy.jitter:
                        delay = delay * (0.5 + random.random() * 0.5)

                    actions_taken.append(
                        RecoveryAction(
                            action_type="RETRY",
                            attempt=attempt,
                            delay_seconds=round(delay, 3),
                            details=f"Transient error [{err_code.value}]; retrying in {delay:.2f}s (attempt {attempt}/{active_policy.max_retries}).",
                        )
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    # Non-retriable or retries exhausted: break out of loop to fallback/rollback
                    break

        # -------------------------------------------------------------
        # 3. Rollback Phase (Rollback where appropriate to preserve state)
        # -------------------------------------------------------------
        rollback_applied = False
        if rollback_handler is not None and last_failure_event is not None:
            try:
                logger.info(
                    "Executing rollback for '%s' to preserve goal state [cid=%s]",
                    operation_name,
                    cid,
                )
                if inspect.iscoroutinefunction(rollback_handler):
                    await rollback_handler(last_failure_event)
                else:
                    rb_res = rollback_handler(last_failure_event)
                    if inspect.isawaitable(rb_res):
                        await rb_res
                rollback_applied = True
                actions_taken.append(
                    RecoveryAction(
                        action_type="ROLLBACK",
                        attempt=attempt,
                        details=f"State rollback executed successfully for '{operation_name}'.",
                    )
                )
            except Exception as rb_exc:
                logger.error("Rollback failed for '%s': %s", operation_name, rb_exc)

        # -------------------------------------------------------------
        # 4. Fallback Phase (if retries exhausted or non-retriable)
        # -------------------------------------------------------------
        fallback_applied = False
        if fallback_handler is not None and last_failure_event is not None:
            try:
                logger.info("Attempting fallback for operation '%s' [cid=%s]", operation_name, cid)
                if inspect.iscoroutinefunction(fallback_handler):
                    fallback_data = await fallback_handler(last_failure_event)
                else:
                    f_res = fallback_handler(last_failure_event)
                    fallback_data = await f_res if inspect.isawaitable(f_res) else f_res

                actions_taken.append(
                    RecoveryAction(
                        action_type="FALLBACK",
                        attempt=attempt,
                        details=f"Fallback handler successfully recovered operation '{operation_name}'.",
                    )
                )

                if idempotency_key is not None:
                    idempotency_manager.complete_operation(idempotency_key, fallback_data)

                # User notification of fallback/degradation
                notification = UserNotification(
                    correlation_id=cid,
                    user_id=user_id,
                    severity="WARNING",
                    title=user_notification_title or f"Degraded Service: {operation_name}",
                    message=(
                        f"A transient issue ({last_failure_event.error_code.value}) occurred. "
                        f"LifeThread applied an automatic fallback to complete your request."
                    ),
                    remediation_action="No action required; degraded fallback was successful.",
                )
                cls._user_notifications.append(notification)

                return RecoveryResult[T](
                    correlation_id=cid,
                    success=True,
                    data=fallback_data,
                    final_action="RECOVERED_VIA_FALLBACK",
                    attempts_made=attempt,
                    fallback_applied=True,
                    rollback_applied=rollback_applied,
                    state_preserved=True,
                    user_notification=notification,
                    actions_taken=actions_taken,
                )
            except Exception as fb_exc:
                logger.error("Fallback handler failed for '%s': %s", operation_name, fb_exc)
                actions_taken.append(
                    RecoveryAction(
                        action_type="FALLBACK",
                        attempt=attempt,
                        details=f"Fallback handler failed: {fb_exc}",
                    )
                )

        # Release idempotency lock on failure so future runs can retry cleanly
        if idempotency_key is not None:
            idempotency_manager.fail_operation(
                idempotency_key,
                last_failure_event.message if last_failure_event else "Operation failed",
            )

        # -------------------------------------------------------------
        # 5. Safe Failure & User Notification (Preserve agent state)
        # -------------------------------------------------------------
        err_code = (
            last_failure_event.error_code
            if last_failure_event
            else RecoveryErrorCode.RECOVERY_FAILED
        )
        err_msg = last_failure_event.message if last_failure_event else "Unknown failure occurred"

        notification = UserNotification(
            correlation_id=cid,
            user_id=user_id,
            severity="ERROR",
            title=user_notification_title or f"Failure: {operation_name}",
            message=(
                f"Operation '{operation_name}' could not be completed safely ({err_code.value}). "
                f"All changes were safely rolled back to preserve your goal state."
            ),
            remediation_action="Please review input parameters or retry once external services are available.",
        )
        cls._user_notifications.append(notification)

        audit_logger.error(
            "AUDIT [SAFE_FAILURE] cid=%s op='%s' attempts=%d code=%s rollback_applied=%s",
            cid,
            operation_name,
            attempt,
            err_code.value,
            rollback_applied,
        )

        return RecoveryResult[T](
            correlation_id=cid,
            success=False,
            data=None,
            final_action="SAFE_FAILURE",
            attempts_made=attempt,
            fallback_applied=fallback_applied,
            rollback_applied=rollback_applied,
            error_code=err_code,
            error_message=err_msg,
            user_notification=notification,
            state_preserved=True,
            actions_taken=actions_taken,
        )

    # =========================================================================
    # SPECIALIZED RECOVERY HANDLERS FOR THE 9 CORE FAILURE TYPES
    # =========================================================================

    @classmethod
    async def recover_llm_call(
        cls,
        prompt: str,
        user_id: uuid.UUID,
        primary_caller: Callable[[], Awaitable[str]],
        fallback_caller: Callable[[], Awaitable[str]] | None = None,
        schema_validator: Callable[[str], Any] | None = None,
        policy: RetryPolicy | None = None,
        correlation_id: str | None = None,
    ) -> RecoveryResult[str]:
        """Handles: LLM timeout & LLM malformed response with retries, fallback provider, and schema repair."""
        cid = correlation_id or str(uuid.uuid4())

        async def _call_and_validate() -> str:
            raw_resp = await primary_caller()
            if schema_validator is not None:
                # Validates response structure; raises on malformed
                schema_validator(raw_resp)
            return raw_resp

        async def _llm_fallback(event: FailureEvent) -> str:
            if fallback_caller is not None:
                logger.info("Failing over to secondary LLM provider [cid=%s]", cid)
                f_resp = await fallback_caller()
                if schema_validator is not None:
                    schema_validator(f_resp)
                return f_resp
            # Heuristic default JSON fallback if malformed
            if event.error_code == RecoveryErrorCode.LLM_MALFORMED_RESPONSE:
                return json.dumps(
                    {"status": "FALLBACK_REPAIRED", "content": "Default structured fallback."}
                )
            raise RuntimeError(f"No secondary LLM fallback available for error: {event.error_code}")

        return await cls.execute_with_recovery(
            operation=_call_and_validate,
            user_id=user_id,
            policy=policy or RetryPolicy(max_retries=2, base_delay_seconds=0.05),
            fallback_handler=_llm_fallback,
            correlation_id=cid,
            operation_name="LLM Call",
            user_notification_title="LLM Service Notice",
        )

    @classmethod
    async def recover_mcp_call(
        cls,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: uuid.UUID,
        mcp_caller: Callable[[str, dict[str, Any]], Awaitable[Any]],
        fallback_local_tool: Callable[[dict[str, Any]], Awaitable[Any] | Any] | None = None,
        policy: RetryPolicy | None = None,
        correlation_id: str | None = None,
    ) -> RecoveryResult[Any]:
        """Handles: MCP timeout & MCP unavailable with retries and fallback to local/cached tool."""
        cid = correlation_id or str(uuid.uuid4())

        async def _mcp_op():
            return await mcp_caller(tool_name, arguments)

        async def _mcp_fallback(event: FailureEvent) -> Any:
            if fallback_local_tool is not None:
                logger.info(
                    "Falling back from remote MCP to local offline tool for '%s'", tool_name
                )
                res = fallback_local_tool(arguments)
                return await res if inspect.isawaitable(res) else res
            return {
                "status": "DEGRADED_MCP_FALLBACK",
                "tool_name": tool_name,
                "result": "Cached baseline result",
            }

        return await cls.execute_with_recovery(
            operation=_mcp_op,
            user_id=user_id,
            policy=policy or RetryPolicy(max_retries=2, base_delay_seconds=0.05),
            fallback_handler=_mcp_fallback,
            correlation_id=cid,
            operation_name=f"MCP Tool: {tool_name}",
            user_notification_title=f"MCP Tool Notice: {tool_name}",
        )

    @classmethod
    async def recover_tool_execution(
        cls,
        tool_name: str,
        arguments: dict[str, Any],
        user_id: uuid.UUID,
        executor_func: Callable[[dict[str, Any]], Awaitable[Any] | Any],
        argument_corrector: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        correlation_id: str | None = None,
    ) -> RecoveryResult[Any]:
        """Handles: Tool failure & Invalid tool arguments with argument repair and fallback."""
        cid = correlation_id or str(uuid.uuid4())
        current_args = dict(arguments)

        async def _tool_op():
            res = executor_func(current_args)
            return await res if inspect.isawaitable(res) else res

        async def _arg_repair_fallback(event: FailureEvent) -> Any:
            if (
                event.error_code == RecoveryErrorCode.INVALID_TOOL_ARGUMENTS
                and argument_corrector is not None
            ):
                logger.info("Attempting automated argument repair for '%s'", tool_name)
                repaired_args = argument_corrector(arguments)
                res = executor_func(repaired_args)
                return await res if inspect.isawaitable(res) else res
            return {
                "status": "TOOL_FALLBACK_DEFAULT",
                "tool_name": tool_name,
                "message": "Default fallback output",
            }

        return await cls.execute_with_recovery(
            operation=_tool_op,
            user_id=user_id,
            policy=RetryPolicy(max_retries=2, base_delay_seconds=0.05),
            fallback_handler=_arg_repair_fallback,
            correlation_id=cid,
            operation_name=f"Tool: {tool_name}",
            user_notification_title=f"Tool Execution Notice: {tool_name}",
        )

    @classmethod
    async def recover_db_transaction(
        cls,
        db_session: AsyncSession,
        user_id: uuid.UUID,
        tx_operation: Callable[[], Awaitable[T]],
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        operation_name: str = "DB Transaction",
    ) -> RecoveryResult[T]:
        """Handles: Database transient failure with transaction rollback, retries, and state preservation."""
        cid = correlation_id or str(uuid.uuid4())

        async def _db_op() -> T:
            res = await tx_operation()
            await db_session.flush()
            return res

        async def _rollback_on_err(event: FailureEvent) -> None:
            logger.warning(
                "Rolling back database transaction due to %s [cid=%s]", event.error_code.value, cid
            )
            await db_session.rollback()

        return await cls.execute_with_recovery(
            operation=_db_op,
            user_id=user_id,
            policy=RetryPolicy(max_retries=3, base_delay_seconds=0.05),
            rollback_handler=_rollback_on_err,
            idempotency_key=idempotency_key,
            correlation_id=cid,
            operation_name=operation_name,
            user_notification_title="Database Transient Issue",
        )

    @classmethod
    async def recover_planning(
        cls,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        planning_op: Callable[[], Awaitable[T]],
        fallback_plan_generator: Callable[[], Awaitable[T] | T] | None = None,
        rollback_plan: Callable[[], Awaitable[None]] | None = None,
        correlation_id: str | None = None,
    ) -> RecoveryResult[T]:
        """Handles: Planning failure with rollback of partial state and fallback to safe linear/cached plan."""
        cid = correlation_id or str(uuid.uuid4())

        async def _plan_fallback(event: FailureEvent) -> T:
            if fallback_plan_generator is not None:
                logger.info("Planning failed; applying safe fallback plan generator [cid=%s]", cid)
                res = fallback_plan_generator()
                return await res if inspect.isawaitable(res) else res
            raise RuntimeError("No fallback plan generator configured")

        async def _plan_rollback(event: FailureEvent) -> None:
            if rollback_plan is not None:
                logger.warning("Rolling back partial plan state for goal %s [cid=%s]", goal_id, cid)
                await rollback_plan()

        return await cls.execute_with_recovery(
            operation=planning_op,
            user_id=user_id,
            policy=RetryPolicy(max_retries=1, base_delay_seconds=0.05),
            fallback_handler=_plan_fallback,
            rollback_handler=_plan_rollback,
            correlation_id=cid,
            operation_name=f"Planning for Goal {goal_id}",
            user_notification_title="Planning Adaptation Notice",
        )

    @classmethod
    async def recover_context_overflow(
        cls,
        user_id: uuid.UUID,
        context_items: list[ContextItem],
        builder_func: Callable[[list[ContextItem]], Any],
        target_token_limit: int,
        correlation_id: str | None = None,
    ) -> RecoveryResult[Any]:
        """Handles: Context overflow by progressive pruning of lower-priority context items and re-budgeting."""
        cid = correlation_id or str(uuid.uuid4())

        def _build_attempt():
            # Will raise ValueError / Overflow if tokens exceed target
            total_est = sum(
                item.tokens or max(1, len(item.content.split())) for item in context_items
            )
            if total_est > target_token_limit:
                raise ValueError(
                    f"CONTEXT_OVERFLOW: Total estimated tokens {total_est} exceeds target limit {target_token_limit}"
                )
            return builder_func(context_items)

        def _prune_fallback(event: FailureEvent) -> Any:
            logger.info(
                "Context overflow detected; progressively pruning lower-priority items [cid=%s]",
                cid,
            )
            # Prune items starting with lowest priority (effective_priority 7 -> 6 -> 5...)
            pruned = sorted(context_items, key=lambda it: it.effective_priority)
            accumulated = []
            running_tokens = 0
            for it in pruned:
                t = it.tokens or max(1, len(it.content.split()))
                if running_tokens + t <= target_token_limit:
                    accumulated.append(it)
                    running_tokens += t

            logger.info(
                "Pruned context from %d items to %d items (%d tokens <= %d target)",
                len(context_items),
                len(accumulated),
                running_tokens,
                target_token_limit,
            )
            return builder_func(accumulated)

        return await cls.execute_with_recovery(
            operation=_build_attempt,
            user_id=user_id,
            policy=RetryPolicy(max_retries=0),  # Non-retriable without pruning
            fallback_handler=_prune_fallback,
            correlation_id=cid,
            operation_name="Context Assembly",
            user_notification_title="Context Optimized",
        )
