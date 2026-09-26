import abc
import logging
import time
import uuid
from typing import Any

from pydantic import BaseModel, ValidationError

from app.services.agent_trace.models import EventStatus, ExecutionEventType
from app.services.agent_trace.service import AgentTraceService
from app.services.skills.models import (
    FailureBehavior,
    SkillCategory,
    SkillExecutionContext,
    SkillMetadata,
    SkillResult,
)

logger = logging.getLogger("lifethread.services.skills")


class AgentSkill(abc.ABC):
    """Abstract Base Class for all LifeThread reusable Agent Skills.

    Defines purpose, inputs/outputs contracts, permissions, tools, and failure behavior.
    """

    name: str
    purpose: str
    category: SkillCategory
    inputs_model: type[BaseModel]
    outputs_model: type[BaseModel]
    required_permissions: list[str] = []
    tools: list[str] = []
    failure_behavior: FailureBehavior = FailureBehavior.FAIL_FAST

    def get_metadata(self) -> SkillMetadata:
        """Produce introspective machine-readable metadata for skill discovery."""
        return SkillMetadata(
            name=self.name,
            purpose=self.purpose,
            category=self.category,
            required_permissions=self.required_permissions,
            tools=self.tools,
            failure_behavior=self.failure_behavior,
            inputs_schema=self.inputs_model.model_json_schema(),
            outputs_schema=self.outputs_model.model_json_schema(),
        )

    def validate_inputs(self, raw_inputs: dict[str, Any] | BaseModel) -> BaseModel:
        """Validate input payload against the skill's defined input schema."""
        if isinstance(raw_inputs, self.inputs_model):
            return raw_inputs
        return self.inputs_model.model_validate(raw_inputs)

    def validate_outputs(self, raw_outputs: dict[str, Any] | BaseModel) -> BaseModel:
        """Validate output payload against the skill's defined output schema."""
        if isinstance(raw_outputs, self.outputs_model):
            return raw_outputs
        return self.outputs_model.model_validate(raw_outputs)

    def check_permissions(self, context: SkillExecutionContext) -> tuple[bool, str | None]:
        """Verify the execution context possesses all permissions required by this skill."""
        if not self.required_permissions:
            return True, None

        # If user_permissions has wildcard "*" or all specific scopes
        if "*" in context.user_permissions:
            return True, None

        missing = [p for p in self.required_permissions if p not in context.user_permissions]
        if missing:
            return False, f"Missing required permissions: {', '.join(missing)}"
        return True, None

    async def execute(
        self,
        context: SkillExecutionContext,
        inputs: dict[str, Any] | BaseModel,
    ) -> SkillResult:
        """Execute the skill with input validation, permission enforcement, tracing, and failure handling."""
        start_time = time.perf_counter()
        trace_events: list[str] = []

        # 1. Permission Enforcement
        has_perm, perm_err = self.check_permissions(context)
        if not has_perm:
            logger.warning("Permission denied for skill '%s': %s", self.name, perm_err)
            return SkillResult(
                skill_name=self.name,
                success=False,
                error=perm_err,
                failure_behavior_applied=FailureBehavior.FAIL_FAST,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        # 2. Input Validation
        try:
            validated_inputs = self.validate_inputs(inputs)
        except ValidationError as val_err:
            logger.error("Input validation failed for skill '%s': %s", self.name, val_err)
            return SkillResult(
                skill_name=self.name,
                success=False,
                error=f"Invalid inputs: {str(val_err)}",
                failure_behavior_applied=FailureBehavior.FAIL_FAST,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        # 3. Tracing Setup
        run_id = context.run_id
        owns_run = False
        if not run_id:
            owns_run = True
            corr_id = context.session_id or f"skill-{uuid.uuid4().hex[:12]}"
            run = AgentTraceService.start_run(
                user_id=context.user_id,
                trigger=f"SKILL:{self.name}",
                goal_id=context.goal_id,
                task_id=context.task_id,
                summary=f"Executing Agent Skill: {self.name}",
                correlation_id=corr_id,
                input_data=validated_inputs.model_dump(),
            )
            run_id = run.id
            context.run_id = run_id

            AgentTraceService.record_selected_context(
                run_id=run_id,
                user_id=context.user_id,
                context={
                    "session_id": context.session_id,
                    "goal_id": str(context.goal_id) if context.goal_id else None,
                    "task_id": str(context.task_id) if context.task_id else None,
                },
                rationale="Skill execution context resolved.",
            )

            AgentTraceService.record_selected_tools(
                run_id=run_id,
                user_id=context.user_id,
                tools=[self.name] + list(self.tools),
                rationale=f"Selected skill '{self.name}' with authorized toolset.",
            )

        # Record DECISION event
        AgentTraceService.record_event(
            run_id=run_id,
            user_id=context.user_id,
            event_type=ExecutionEventType.DECISION,
            status=EventStatus.SUCCESS,
            short_explanation=f"Selected and initialized skill '{self.name}'.",
            goal_id=context.goal_id,
            metadata={"skill_name": self.name, "category": self.category.value, "tools": self.tools},
        )
        trace_events.append("DECISION:skill_selected")

        # 4. Core Execution with Failure Behavior
        try:
            raw_output = await self._execute_internal(context, validated_inputs)
            validated_output = self.validate_outputs(raw_output)

            # Record STATE_UPDATE trace
            AgentTraceService.record_event(
                run_id=run_id,
                user_id=context.user_id,
                event_type=ExecutionEventType.STATE_UPDATE,
                status=EventStatus.SUCCESS,
                short_explanation=f"Skill '{self.name}' completed successfully.",
                goal_id=context.goal_id,
            )
            trace_events.append("STATE_UPDATE:completed")

            if owns_run:
                AgentTraceService.record_final_result(
                    run_id=run_id,
                    user_id=context.user_id,
                    final_result=validated_output.model_dump(),
                    rationale=f"Skill '{self.name}' completed successfully.",
                )
                AgentTraceService.finish_run(run_id=run_id, user_id=context.user_id, status=EventStatus.SUCCESS)

            execution_time = (time.perf_counter() - start_time) * 1000
            return SkillResult(
                skill_name=self.name,
                success=True,
                data=validated_output.model_dump(),
                execution_time_ms=execution_time,
                trace_events=trace_events,
            )

        except Exception as exc:
            logger.exception("Error executing skill '%s': %s", self.name, exc)
            if owns_run:
                AgentTraceService.record_final_result(
                    run_id=run_id,
                    user_id=context.user_id,
                    final_result={"error": str(exc)},
                    rationale=f"Skill '{self.name}' execution failed.",
                )
                AgentTraceService.finish_run(run_id=run_id, user_id=context.user_id, status=EventStatus.FAILED)
            return await self._handle_failure(context, validated_inputs, exc, start_time, trace_events)
            return await self._handle_failure(context, validated_inputs, exc, start_time, trace_events)

    async def _handle_failure(
        self,
        context: SkillExecutionContext,
        inputs: BaseModel,
        exc: Exception,
        start_time: float,
        trace_events: list[str],
    ) -> SkillResult:
        """Handle execution failure according to the skill's declared FailureBehavior."""
        run_id = context.run_id or ""
        error_msg = str(exc)

        AgentTraceService.record_event(
            run_id=run_id,
            user_id=context.user_id,
            event_type=ExecutionEventType.EVALUATION,
            status=EventStatus.FAILED,
            short_explanation=f"Skill '{self.name}' encountered error: {error_msg}",
            goal_id=context.goal_id,
            metadata={"failure_behavior": self.failure_behavior.value},
        )
        trace_events.append("EVALUATION:failed")

        if self.failure_behavior == FailureBehavior.FALLBACK_DEFAULT:
            logger.info("Applying FALLBACK_DEFAULT for skill '%s'", self.name)
            fallback_data = await self._fallback_default(context, inputs, exc)
            trace_events.append("FALLBACK:applied")
            return SkillResult(
                skill_name=self.name,
                success=True,
                data=fallback_data,
                error=error_msg,
                failure_behavior_applied=FailureBehavior.FALLBACK_DEFAULT,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
                trace_events=trace_events,
            )

        elif self.failure_behavior == FailureBehavior.GRACEFUL_DEGRADATION:
            logger.info("Applying GRACEFUL_DEGRADATION for skill '%s'", self.name)
            degraded_data = await self._graceful_degrade(context, inputs, exc)
            trace_events.append("DEGRADATION:applied")
            return SkillResult(
                skill_name=self.name,
                success=True,
                data=degraded_data,
                error=error_msg,
                failure_behavior_applied=FailureBehavior.GRACEFUL_DEGRADATION,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
                trace_events=trace_events,
            )

        # FAIL_FAST or ROLLBACK_AND_NOTIFY
        return SkillResult(
            skill_name=self.name,
            success=False,
            error=error_msg,
            failure_behavior_applied=self.failure_behavior,
            execution_time_ms=(time.perf_counter() - start_time) * 1000,
            trace_events=trace_events,
        )

    @abc.abstractmethod
    async def _execute_internal(
        self,
        context: SkillExecutionContext,
        inputs: Any,
    ) -> Any:
        """Concrete skill implementation logic."""
        pass

    async def _fallback_default(
        self,
        context: SkillExecutionContext,
        inputs: Any,
        exc: Exception,
    ) -> dict[str, Any]:
        """Default fallback hook when failure_behavior is FALLBACK_DEFAULT."""
        return {"fallback": True, "error": str(exc)}

    async def _graceful_degrade(
        self,
        context: SkillExecutionContext,
        inputs: Any,
        exc: Exception,
    ) -> dict[str, Any]:
        """Graceful degradation hook when failure_behavior is GRACEFUL_DEGRADATION."""
        return {"degraded": True, "error": str(exc)}
