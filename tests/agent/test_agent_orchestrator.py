import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

import pytest
from lifethread_agent.models import (
    AgentDecision,
    AgentRun,
    AgentState,
    AgentStep,
    StepEvaluation,
    ToolExecutionResult,
)
from lifethread_agent.orchestrator import AgentOrchestrator
from lifethread_agent.policy import (
    DeterministicSequencePolicy,
    DynamicRulePolicy,
    MockToolPolicy,
)
from lifethread_agent.ports import (
    EvaluationPort,
    MemoryPort,
    StateRetrievalPort,
    ToolExecutionPort,
)
from lifethread_agent.runtime import AgentRuntime
from lifethread_agent.state_machine import (
    AgentStateMachine,
    CancellationToken,
    InvalidStateTransitionError,
)
from lifethread_agent.types import AgentStatus, DecisionType

# ============================================================================
# MOCK PORTS (Decoupled, in-memory implementations)
# ============================================================================


class InMemoryStatePort(StateRetrievalPort):
    def __init__(self, initial_state: AgentState | None = None) -> None:
        self.state_store: dict[str, AgentState] = {}
        if initial_state:
            key = f"{initial_state.goal_id}:{initial_state.user_id}"
            self.state_store[key] = initial_state
        self.update_calls: list[tuple[str, AgentState]] = []

    async def get_state(self, goal_id: str, user_id: str) -> AgentState:
        key = f"{goal_id}:{user_id}"
        if key in self.state_store:
            return self.state_store[key]
        state = AgentState(goal_id=goal_id, user_id=user_id)
        self.state_store[key] = state
        return state

    async def update_state(self, run_id: str, state: AgentState) -> None:
        self.update_calls.append((run_id, state))
        key = f"{state.goal_id}:{state.user_id}"
        self.state_store[key] = state


class InMemoryToolPort(ToolExecutionPort):
    def __init__(self, available_tools: list[str] | None = None) -> None:
        self.available_tools = available_tools or [
            "search_knowledge",
            "calculate_schedule",
            "send_notification",
        ]
        self.execution_log: list[dict[str, Any]] = []

    async def get_available_tools(self) -> list[str]:
        return list(self.available_tools)

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> ToolExecutionResult:
        self.execution_log.append({"tool": tool_name, "args": arguments, "context": context})

        if tool_name == "slow_tool":
            await asyncio.sleep(arguments.get("sleep_seconds", 0.5))

        if tool_name == "error_tool":
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                error="Simulated tool operational failure",
            )

        return ToolExecutionResult(
            tool_name=tool_name,
            success=True,
            result={
                "status": "success",
                "echo_args": arguments,
                "processed_at": datetime.now(UTC).isoformat(),
            },
            execution_time_ms=12.5,
        )


class InMemoryEvaluationPort(EvaluationPort):
    def __init__(self, terminal_on_step: int | None = None) -> None:
        self.terminal_on_step = terminal_on_step
        self.evaluations_performed: list[StepEvaluation] = []

    async def evaluate_step(
        self,
        step: AgentStep,
        current_state: AgentState,
    ) -> StepEvaluation:
        action_success = (
            step.action_result.success
            if isinstance(step.action_result, ToolExecutionResult)
            else True
        )
        is_terminal = (
            self.terminal_on_step is not None and step.step_number >= self.terminal_on_step
        )

        evaluation = StepEvaluation(
            is_successful=action_success,
            progress_made=action_success,
            is_terminal=is_terminal,
            evaluation_notes=f"Evaluated step {step.step_number} successfully.",
        )
        self.evaluations_performed.append(evaluation)
        return evaluation


class InMemoryMemoryPort(MemoryPort):
    def __init__(self) -> None:
        self.memories: list[dict[str, Any]] = []
        self.recorded_interactions: list[dict[str, Any]] = []

    async def retrieve_context(
        self,
        query: str,
        user_id: str,
        goal_id: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "context_id": "ctx-1",
                "content": f"Relevant historical context for query {query}",
            }
        ]

    async def record_interaction(self, run_id: str, step: AgentStep) -> None:
        self.recorded_interactions.append({"run_id": run_id, "step": step.model_dump()})


# ============================================================================
# TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_controlled_agent_run_executes_actions_and_terminates_safely():
    """Acceptance Criteria: A controlled agent run executes a sequence of mocked actions and terminates safely."""
    state_port = InMemoryStatePort()
    tool_port = InMemoryToolPort()
    eval_port = InMemoryEvaluationPort()
    memory_port = InMemoryMemoryPort()

    # Predefined 2-action sequence followed by finish
    policy = DeterministicSequencePolicy(
        [
            AgentDecision(
                decision_type=DecisionType.CALL_TOOL,
                tool_name="search_knowledge",
                tool_args={"query": "system design resources"},
                reasoning="Step 1: Retrieve domain materials",
            ),
            AgentDecision(
                decision_type=DecisionType.CALL_TOOL,
                tool_name="calculate_schedule",
                tool_args={"duration_days": 10},
                reasoning="Step 2: Calculate timeline estimation",
            ),
            AgentDecision(
                decision_type=DecisionType.FINISH,
                reasoning="All required work completed safely",
            ),
        ]
    )

    runtime = AgentRuntime(
        state_port=state_port,
        tool_port=tool_port,
        eval_port=eval_port,
        memory_port=memory_port,
        decision_policy=policy,
        max_iterations=10,
    )

    orchestrator = AgentOrchestrator(orchestrator_id="acceptance-orch")
    run = orchestrator.create_run(
        goal_id="goal-accept-001",
        user_id="user-001",
        initial_variables={"starting_phase": "bootstrapped"},
    )

    completed_run = await orchestrator.execute_run(run=run, runtime=runtime)

    # Verifications
    assert completed_run.status == AgentStatus.COMPLETED
    assert completed_run.error is None
    assert completed_run.iteration_count == 3
    assert completed_run.started_at is not None
    assert completed_run.completed_at is not None

    # Verifications of tool execution
    assert len(tool_port.execution_log) == 2
    assert tool_port.execution_log[0]["tool"] == "search_knowledge"
    assert tool_port.execution_log[1]["tool"] == "calculate_schedule"

    # Verifications of state updates
    assert "tool_result_search_knowledge_1" in completed_run.state.variables
    assert "tool_result_calculate_schedule_2" in completed_run.state.variables
    assert len(state_port.update_calls) == 2

    # Verifications of memory recordings
    assert len(memory_port.recorded_interactions) == 2

    # Verifications of trace & step logging
    assert len(completed_run.steps) > 0
    phases = [s.phase.value for s in completed_run.steps]
    assert "observe" in phases
    assert "understand" in phases
    assert "decide" in phases
    assert "act" in phases
    assert "evaluate" in phases
    assert "update_state" in phases

    # Check state transitions recorded in trace
    transitions = [e for e in completed_run.trace if e.get("type") == "state_transition"]
    assert len(transitions) >= 2
    assert transitions[0]["to_status"] == "running"
    assert transitions[-1]["to_status"] == "completed"


@pytest.mark.asyncio
async def test_iteration_limit_prevents_runaway_loops():
    """Agent runtime safely halts when iteration limit is reached."""
    state_port = InMemoryStatePort()
    tool_port = InMemoryToolPort()
    eval_port = InMemoryEvaluationPort()
    memory_port = InMemoryMemoryPort()

    # Policy that attempts to call tools infinitely
    policy = MockToolPolicy(
        tool_name="search_knowledge",
        tool_args={"q": "infinite"},
        max_tool_calls=100,  # Far exceeds max_iterations
    )

    runtime = AgentRuntime(
        state_port=state_port,
        tool_port=tool_port,
        eval_port=eval_port,
        memory_port=memory_port,
        decision_policy=policy,
        max_iterations=4,  # Hard limit 4 iterations
        loop_repetition_threshold=10,  # Ensure loop guard doesn't trigger before iteration limit
    )

    orchestrator = AgentOrchestrator()
    run = orchestrator.create_run(goal_id="goal-limit-01", user_id="user-01")

    completed_run = await orchestrator.execute_run(run=run, runtime=runtime)

    assert completed_run.status == AgentStatus.FAILED
    assert completed_run.iteration_count == 4
    assert completed_run.error is not None
    assert "max iteration limit" in completed_run.error.lower()


@pytest.mark.asyncio
async def test_infinite_loop_guard_detects_repetitive_decisions():
    """Loop guard detects cyclic/repetitive decisions and halts safely."""
    state_port = InMemoryStatePort()
    tool_port = InMemoryToolPort()
    eval_port = InMemoryEvaluationPort()
    memory_port = InMemoryMemoryPort()

    # Policy that sends identical decisions repeatedly
    policy = DynamicRulePolicy(
        rule_func=lambda state, tools, steps: AgentDecision(
            decision_type=DecisionType.CALL_TOOL,
            tool_name="search_knowledge",
            tool_args={"topic": "stuck_in_loop"},
            reasoning="Repeating exact same action without variation",
        )
    )

    runtime = AgentRuntime(
        state_port=state_port,
        tool_port=tool_port,
        eval_port=eval_port,
        memory_port=memory_port,
        decision_policy=policy,
        max_iterations=10,
        loop_repetition_threshold=3,  # Trigger on 3rd identical decision
    )

    orchestrator = AgentOrchestrator()
    run = orchestrator.create_run(goal_id="goal-loop-01", user_id="user-01")

    completed_run = await orchestrator.execute_run(run=run, runtime=runtime)

    assert completed_run.status == AgentStatus.FAILED
    assert completed_run.error is not None
    assert "loop detected" in completed_run.error.lower()


@pytest.mark.asyncio
async def test_cancellation_token_stops_run():
    """Cancellation token halts execution between phases immediately."""
    state_port = InMemoryStatePort()
    tool_port = InMemoryToolPort()
    eval_port = InMemoryEvaluationPort()
    memory_port = InMemoryMemoryPort()

    token = CancellationToken()

    def cancelling_rule(
        state: AgentState, tools: list[str], steps: list[AgentStep]
    ) -> AgentDecision:
        # Cancel token during decision step of iteration 1
        token.cancel(reason="User pressed stop button")
        return AgentDecision(
            decision_type=DecisionType.CALL_TOOL,
            tool_name="search_knowledge",
            tool_args={"q": "should cancel before next act"},
            reasoning="Attempting tool call while cancelling",
        )

    policy = DynamicRulePolicy(rule_func=cancelling_rule)

    runtime = AgentRuntime(
        state_port=state_port,
        tool_port=tool_port,
        eval_port=eval_port,
        memory_port=memory_port,
        decision_policy=policy,
        max_iterations=5,
    )

    orchestrator = AgentOrchestrator()
    run = orchestrator.create_run(goal_id="goal-cancel-01", user_id="user-01")

    completed_run = await orchestrator.execute_run(
        run=run, runtime=runtime, cancellation_token=token
    )

    assert completed_run.status == AgentStatus.CANCELLED
    assert completed_run.completed_at is not None
    # Verify that tool execution was averted after token was checked
    assert len(tool_port.execution_log) == 0


@pytest.mark.asyncio
async def test_timeout_handling_safely_terminates_run():
    """Run exceeding max_run_seconds transitions to TIMEOUT status."""
    state_port = InMemoryStatePort()
    tool_port = InMemoryToolPort(available_tools=["search_knowledge", "slow_tool"])
    eval_port = InMemoryEvaluationPort()
    memory_port = InMemoryMemoryPort()

    # Tool execution that sleeps longer than timeout
    policy = DeterministicSequencePolicy(
        [
            AgentDecision(
                decision_type=DecisionType.CALL_TOOL,
                tool_name="slow_tool",
                tool_args={"sleep_seconds": 1.5},
                reasoning="Testing run timeout",
            )
        ]
    )

    runtime = AgentRuntime(
        state_port=state_port,
        tool_port=tool_port,
        eval_port=eval_port,
        memory_port=memory_port,
        decision_policy=policy,
        max_iterations=5,
        max_run_seconds=0.2,  # Very short run timeout
        step_timeout_seconds=5.0,
    )

    orchestrator = AgentOrchestrator()
    run = orchestrator.create_run(goal_id="goal-timeout-01", user_id="user-01")

    completed_run = await orchestrator.execute_run(run=run, runtime=runtime)

    assert completed_run.status == AgentStatus.TIMEOUT
    assert completed_run.error is not None
    assert "timed out" in completed_run.error.lower() or "timeout" in completed_run.error.lower()


@pytest.mark.asyncio
async def test_unapproved_tool_execution_handled_gracefully():
    """Requesting an unapproved tool records an error without crashing the runtime."""
    state_port = InMemoryStatePort()
    tool_port = InMemoryToolPort(available_tools=["search_knowledge"])  # only search allowed
    eval_port = InMemoryEvaluationPort()
    memory_port = InMemoryMemoryPort()

    policy = DeterministicSequencePolicy(
        [
            AgentDecision(
                decision_type=DecisionType.CALL_TOOL,
                tool_name="unapproved_delete_db",  # not in available tools
                tool_args={},
                reasoning="Attempting forbidden action",
            ),
            AgentDecision(
                decision_type=DecisionType.FINISH,
                reasoning="Conclude after error noted",
            ),
        ]
    )

    runtime = AgentRuntime(
        state_port=state_port,
        tool_port=tool_port,
        eval_port=eval_port,
        memory_port=memory_port,
        decision_policy=policy,
        max_iterations=5,
    )

    orchestrator = AgentOrchestrator()
    run = orchestrator.create_run(goal_id="goal-unapproved-01", user_id="user-01")

    completed_run = await orchestrator.execute_run(run=run, runtime=runtime)

    assert completed_run.status == AgentStatus.COMPLETED
    # Check that ACT step caught unapproved tool
    act_steps = [s for s in completed_run.steps if s.phase.value == "act"]
    assert len(act_steps) == 1
    assert act_steps[0].action_result is not None
    assert act_steps[0].action_result.success is False
    assert "not in approved tools catalog" in act_steps[0].action_result.error


@pytest.mark.asyncio
async def test_state_machine_illegal_transition_raises():
    """State machine raises InvalidStateTransitionError when attempting illegal transitions."""
    run = AgentRun(
        run_id="run-test-sm",
        goal_id="goal-1",
        user_id="user-1",
        status=AgentStatus.COMPLETED,  # Terminal
        state=AgentState(goal_id="goal-1", user_id="user-1"),
    )

    # Attempting to move from COMPLETED to RUNNING is illegal
    with pytest.raises(InvalidStateTransitionError):
        AgentStateMachine.transition(run, AgentStatus.RUNNING, reason="Illegal resume")


def test_zero_database_dependency_in_agent_package():
    """Architecture Rule: lifethread_agent must contain zero database/ORM imports."""
    # Ensure lifethread_agent package can be loaded without sqlalchemy or psycopg
    assert "lifethread_agent" in sys.modules
    for module_name in list(sys.modules.keys()):
        if module_name.startswith("lifethread_agent."):
            mod = sys.modules[module_name]
            # Check module doesn't import sqlalchemy
            imported_names = dir(mod)
            assert "sqlalchemy" not in imported_names
            assert "BaseDBModel" not in imported_names
