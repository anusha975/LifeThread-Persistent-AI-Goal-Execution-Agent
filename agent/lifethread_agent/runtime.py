import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from lifethread_agent.models import (
    AgentDecision,
    AgentRun,
    AgentStep,
    StepEvaluation,
    ToolExecutionResult,
)
from lifethread_agent.policy import DecisionPolicyPort
from lifethread_agent.ports import (
    EvaluationPort,
    MemoryPort,
    StateRetrievalPort,
    ToolExecutionPort,
)
from lifethread_agent.state_machine import (
    AgentStateMachine,
    CancellationToken,
    LoopDetectedError,
    LoopGuard,
)
from lifethread_agent.types import AgentStatus, AgentStepType, DecisionType

logger = logging.getLogger("lifethread.agent.runtime")


class AgentRuntime:
    """Core Agent Execution Runtime.

    Executes the canonical agent loop:
    OBSERVE -> UNDERSTAND -> DECIDE -> ACT -> EVALUATE -> UPDATE STATE

    Fully decoupled from database and storage layers via abstract service ports.
    """

    def __init__(
        self,
        state_port: StateRetrievalPort,
        tool_port: ToolExecutionPort,
        eval_port: EvaluationPort,
        memory_port: MemoryPort,
        decision_policy: DecisionPolicyPort,
        max_iterations: int = 20,
        max_run_seconds: float = 300.0,
        step_timeout_seconds: float = 30.0,
        loop_repetition_threshold: int = 3,
    ) -> None:
        self.state_port = state_port
        self.tool_port = tool_port
        self.eval_port = eval_port
        self.memory_port = memory_port
        self.decision_policy = decision_policy
        self.max_iterations = max_iterations
        self.max_run_seconds = max_run_seconds
        self.step_timeout_seconds = step_timeout_seconds
        self.loop_guard = LoopGuard(repetition_threshold=loop_repetition_threshold)

    async def run(
        self,
        run: AgentRun,
        cancellation_token: CancellationToken | None = None,
    ) -> AgentRun:
        """Execute the agent loop until termination, completion, cancellation, or failure."""
        token = cancellation_token or CancellationToken()

        # Initial transition to RUNNING
        if run.status == AgentStatus.PENDING:
            AgentStateMachine.transition(run, AgentStatus.RUNNING, reason="Starting agent runtime")

        try:
            # Wrap entire run with overall timeout
            async with asyncio.timeout(self.max_run_seconds):
                await self._execution_loop(run, token)

        except TimeoutError:
            msg = f"Run exceeded maximum duration timeout of {self.max_run_seconds}s"
            logger.warning(f"Run [{run.run_id}] timed out: {msg}")
            if AgentStateMachine.can_transition(run.status, AgentStatus.TIMEOUT):
                AgentStateMachine.transition(
                    run,
                    AgentStatus.TIMEOUT,
                    reason="Execution timeout reached",
                    error_details=msg,
                )

        except LoopDetectedError as e:
            logger.error(f"Run [{run.run_id}] loop detected: {e}")
            if AgentStateMachine.can_transition(run.status, AgentStatus.FAILED):
                AgentStateMachine.transition(
                    run,
                    AgentStatus.FAILED,
                    reason="Infinite loop detected",
                    error_details=str(e),
                )

        except Exception as e:
            logger.exception(f"Unhandled exception during agent run [{run.run_id}]: {e}")
            if AgentStateMachine.can_transition(run.status, AgentStatus.FAILED):
                AgentStateMachine.transition(
                    run,
                    AgentStatus.FAILED,
                    reason="Unexpected runtime exception",
                    error_details=str(e),
                )

        return run

    async def _execution_loop(self, run: AgentRun, token: CancellationToken) -> None:
        """Internal execution loop advancing iterations through the 6 phases."""
        while run.status == AgentStatus.RUNNING and not run.state.is_terminal:
            # 1. Check cancellation before iteration
            if token.is_cancelled:
                AgentStateMachine.transition(
                    run,
                    AgentStatus.CANCELLED,
                    reason=token.reason or "Cancellation token activated",
                )
                break

            # 2. Check iteration limits
            if run.iteration_count >= self.max_iterations:
                msg = f"Run exceeded max iteration limit ({self.max_iterations})"
                logger.warning(f"Run [{run.run_id}] reached iteration limit: {msg}")
                AgentStateMachine.transition(
                    run,
                    AgentStatus.FAILED,
                    reason="Max iteration limit exceeded",
                    error_details=msg,
                )
                break

            run.iteration_count += 1
            iteration_index = run.iteration_count
            logger.info(f"Run [{run.run_id}] starting iteration {iteration_index}")

            # Execute single iteration pass
            terminated = await self._execute_iteration(run, iteration_index, token)
            if terminated:
                break

    async def _execute_iteration(
        self,
        run: AgentRun,
        iteration_index: int,
        token: CancellationToken,
    ) -> bool:
        """Executes one pass through: OBSERVE -> UNDERSTAND -> DECIDE -> ACT -> EVALUATE -> UPDATE STATE.

        Returns True if the run reached a terminal status and should exit.
        """
        # ==========================================
        # PHASE 1: OBSERVE
        # ==========================================
        if token.is_cancelled:
            AgentStateMachine.transition(
                run, AgentStatus.CANCELLED, reason=token.reason or "Cancelled before OBSERVE"
            )
            return True

        observe_step = self._start_step(run, AgentStepType.OBSERVE)
        try:
            # Query domain state and memory context
            synced_state = await self.state_port.get_state(run.goal_id, run.user_id)
            context_memories = await self.memory_port.retrieve_context(
                query=f"goal:{run.goal_id}", user_id=run.user_id, goal_id=run.goal_id
            )
            observation = {
                "variables": synced_state.variables,
                "current_task_id": synced_state.current_task_id,
                "context_memories": context_memories,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            run.state.last_observation = observation
            observe_step.output_state = {"observation": observation}
        except Exception as e:
            observe_step.error = f"Observation error: {e}"
            logger.error(f"Error in OBSERVE phase for run {run.run_id}: {e}")
        finally:
            self._complete_step(run, observe_step)

        # ==========================================
        # PHASE 2: UNDERSTAND
        # ==========================================
        if token.is_cancelled:
            AgentStateMachine.transition(
                run, AgentStatus.CANCELLED, reason=token.reason or "Cancelled before UNDERSTAND"
            )
            return True

        understand_step = self._start_step(run, AgentStepType.UNDERSTAND)
        try:
            # Working synthesis of state variables and active task
            understanding = {
                "goal_id": run.goal_id,
                "active_task": run.state.current_task_id,
                "known_variables": list(run.state.variables.keys()),
                "iteration": iteration_index,
            }
            understand_step.output_state = {"understanding": understanding}
        except Exception as e:
            understand_step.error = f"Understanding error: {e}"
        finally:
            self._complete_step(run, understand_step)

        # ==========================================
        # PHASE 3: DECIDE
        # ==========================================
        if token.is_cancelled:
            AgentStateMachine.transition(
                run, AgentStatus.CANCELLED, reason=token.reason or "Cancelled before DECIDE"
            )
            return True

        decide_step = self._start_step(run, AgentStepType.DECIDE)
        decision: AgentDecision | None = None
        try:
            available_tools = await self.tool_port.get_available_tools()
            decision = await self.decision_policy.decide(
                state=run.state,
                available_tools=available_tools,
                recent_steps=run.steps[-5:],
            )
            decide_step.decision = decision

            # Enforce loop guard
            self.loop_guard.record_decision(decision)

        except LoopDetectedError:
            decide_step.error = "Infinite loop detected by loop guard"
            self._complete_step(run, decide_step)
            raise
        except Exception as e:
            decide_step.error = f"Decision error: {e}"
            self._complete_step(run, decide_step)
            AgentStateMachine.transition(
                run, AgentStatus.FAILED, reason="Decision policy error", error_details=str(e)
            )
            return True
        finally:
            self._complete_step(run, decide_step)

        if decision is None:
            AgentStateMachine.transition(
                run, AgentStatus.FAILED, reason="No decision produced by policy"
            )
            return True

        # Handle non-tool decision outcomes
        if decision.decision_type == DecisionType.FINISH:
            run.state.is_terminal = True
            AgentStateMachine.transition(
                run, AgentStatus.COMPLETED, reason=f"Decision: {decision.reasoning}"
            )
            return True

        if decision.decision_type == DecisionType.WAIT_USER:
            AgentStateMachine.transition(
                run, AgentStatus.PAUSED, reason=f"Waiting on user: {decision.reasoning}"
            )
            return True

        if decision.decision_type == DecisionType.FAIL:
            AgentStateMachine.transition(
                run,
                AgentStatus.FAILED,
                reason="Policy decided failure",
                error_details=decision.reasoning,
            )
            return True

        # ==========================================
        # PHASE 4: ACT (CALL_TOOL)
        # ==========================================
        if token.is_cancelled:
            AgentStateMachine.transition(
                run, AgentStatus.CANCELLED, reason=token.reason or "Cancelled before ACT"
            )
            return True

        act_step = self._start_step(run, AgentStepType.ACT)
        act_step.decision = decision
        tool_result: ToolExecutionResult

        try:
            available_tools = await self.tool_port.get_available_tools()
            if not decision.tool_name or decision.tool_name not in available_tools:
                tool_result = ToolExecutionResult(
                    tool_name=decision.tool_name or "unknown",
                    success=False,
                    error=(
                        f"Tool '{decision.tool_name}' is not in approved tools catalog: {available_tools}"
                    ),
                )
            else:
                async with asyncio.timeout(self.step_timeout_seconds):
                    tool_result = await self.tool_port.execute_tool(
                        tool_name=decision.tool_name,
                        arguments=decision.tool_args,
                        context={"run_id": run.run_id, "goal_id": run.goal_id},
                    )

            act_step.action_result = tool_result
            if not tool_result.success:
                act_step.error = tool_result.error
        except TimeoutError:
            tool_result = ToolExecutionResult(
                tool_name=decision.tool_name or "unknown",
                success=False,
                error=f"Step execution timed out after {self.step_timeout_seconds}s",
            )
            act_step.action_result = tool_result
            act_step.error = tool_result.error
        except Exception as e:
            tool_result = ToolExecutionResult(
                tool_name=decision.tool_name or "unknown",
                success=False,
                error=f"Tool execution exception: {e}",
            )
            act_step.action_result = tool_result
            act_step.error = str(e)
        finally:
            self._complete_step(run, act_step)

        # ==========================================
        # PHASE 5: EVALUATE
        # ==========================================
        if token.is_cancelled:
            AgentStateMachine.transition(
                run, AgentStatus.CANCELLED, reason=token.reason or "Cancelled before EVALUATE"
            )
            return True

        eval_step = self._start_step(run, AgentStepType.EVALUATE)
        evaluation: StepEvaluation
        try:
            evaluation = await self.eval_port.evaluate_step(act_step, run.state)
            eval_step.evaluation = evaluation
            run.state.last_evaluation = evaluation.model_dump()
        except Exception as e:
            logger.error(f"Error in EVALUATE phase for run {run.run_id}: {e}")
            evaluation = StepEvaluation(
                is_successful=tool_result.success,
                progress_made=tool_result.success,
                evaluation_notes=f"Default fallback evaluation (eval port error: {e})",
            )
            eval_step.evaluation = evaluation
            eval_step.error = str(e)
        finally:
            self._complete_step(run, eval_step)

        # ==========================================
        # PHASE 6: UPDATE STATE
        # ==========================================
        if token.is_cancelled:
            AgentStateMachine.transition(
                run, AgentStatus.CANCELLED, reason=token.reason or "Cancelled before UPDATE_STATE"
            )
            return True

        update_step = self._start_step(run, AgentStepType.UPDATE_STATE)
        try:
            # Incorporate results into state variables
            if tool_result.success and tool_result.result is not None:
                tool_key = f"tool_result_{decision.tool_name}_{run.iteration_count}"
                run.state.variables[tool_key] = tool_result.result

            # Check if evaluation indicates completion
            if evaluation.is_terminal:
                run.state.is_terminal = True

            # Persist state update via port
            await self.state_port.update_state(run.run_id, run.state)

            # Record interaction trace into memory
            await self.memory_port.record_interaction(run.run_id, act_step)

            update_step.output_state = {
                "variables_count": len(run.state.variables),
                "is_terminal": run.state.is_terminal,
            }
        except Exception as e:
            update_step.error = f"State update error: {e}"
            logger.error(f"Error in UPDATE_STATE for run {run.run_id}: {e}")
        finally:
            self._complete_step(run, update_step)

        # Conclude run if evaluation declared terminal
        if run.state.is_terminal:
            status = AgentStatus.COMPLETED if evaluation.is_successful else AgentStatus.FAILED
            AgentStateMachine.transition(
                run,
                status,
                reason=f"Terminal state reached: {evaluation.evaluation_notes}",
            )
            return True

        return False

    def _start_step(self, run: AgentRun, phase: AgentStepType) -> AgentStep:
        """Create and start a new step tracking entry."""
        run.current_step += 1
        step = AgentStep(
            step_number=run.current_step,
            phase=phase,
            started_at=datetime.now(UTC),
            input_state={"variables": dict(run.state.variables)},
        )
        return step

    def _complete_step(self, run: AgentRun, step: AgentStep) -> None:
        """Finalize and append a step into the run history and execution trace."""
        step.completed_at = datetime.now(UTC)
        run.steps.append(step)

        event: dict[str, Any] = {
            "type": "step_executed",
            "step_number": step.step_number,
            "phase": step.phase.value,
            "duration_ms": (
                (step.completed_at - step.started_at).total_seconds() * 1000
                if step.completed_at
                else 0
            ),
        }
        if step.decision:
            event["decision_type"] = step.decision.decision_type.value
            event["tool_name"] = step.decision.tool_name
        if step.action_result:
            event["action_success"] = (
                step.action_result.success
                if isinstance(step.action_result, ToolExecutionResult)
                else step.action_result.get("success")
            )
        if step.error:
            event["error"] = step.error

        run.trace.append(event)
