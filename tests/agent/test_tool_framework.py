import asyncio
from typing import Any

import pytest
from lifethread_agent.models import AgentDecision, AgentState, AgentStep, StepEvaluation
from lifethread_agent.orchestrator import AgentOrchestrator
from lifethread_agent.policy import DeterministicSequencePolicy
from lifethread_agent.ports import EvaluationPort, MemoryPort, StateRetrievalPort
from lifethread_agent.runtime import AgentRuntime
from lifethread_agent.state_machine import CancellationToken
from lifethread_agent.tools import (
    GenericToolExecutionAdapter,
    RetryPolicy,
    ToolCall,
    ToolErrorCode,
    ToolExecutor,
    ToolPermissionLevel,
    ToolRegistry,
)
from lifethread_agent.types import AgentStatus, DecisionType
from pydantic import BaseModel, Field

# ============================================================================
# SCHEMAS FOR TEST TOOLS
# ============================================================================


class CalculatorInput(BaseModel):
    operation: str = Field(..., description="add, subtract, multiply, divide")
    a: float = Field(..., description="First operand")
    b: float = Field(..., description="Second operand")


class CalculatorOutput(BaseModel):
    result: float
    operation: str


class SensitiveInput(BaseModel):
    resource_id: str
    action: str


# ============================================================================
# UNIT TESTS: TOOL REGISTRY & EXECUTOR
# ============================================================================


@pytest.mark.asyncio
async def test_tool_registration_and_discovery():
    registry = ToolRegistry()

    @registry.tool(
        name="calculate",
        description="Perform arithmetic operations",
        input_schema=CalculatorInput,
        output_schema=CalculatorOutput,
        permission_level=ToolPermissionLevel.READ_ONLY,
        timeout=5.0,
    )
    async def calculate(a: float, b: float, operation: str) -> dict[str, Any]:
        if operation == "add":
            return {"result": a + b, "operation": operation}
        return {"result": a - b, "operation": operation}

    # Verify discovery
    tool = registry.get("calculate")
    assert tool is not None
    assert tool.name == "calculate"
    assert tool.permission_level == ToolPermissionLevel.READ_ONLY
    assert tool.timeout == 5.0

    # Verify listing and schemas
    names = registry.list_tool_names()
    assert "calculate" in names

    schemas = registry.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "calculate"
    assert "properties" in schemas[0]["parameters"]
    assert "operation" in schemas[0]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_tool_input_validation():
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    @registry.tool(
        name="calc",
        description="Calculator",
        input_schema=CalculatorInput,
    )
    async def calc(a: float, b: float, operation: str) -> float:
        return a + b

    # 1. Valid input
    valid_call = ToolCall(
        tool_name="calc",
        arguments={"a": 10.5, "b": 2.5, "operation": "add"},
    )
    result = await executor.execute(valid_call)
    assert result.success is True
    assert result.data == 13.0
    assert result.error is None
    assert result.execution_time_ms > 0

    # 2. Invalid input (missing field 'b' and invalid type for 'a')
    invalid_call = ToolCall(
        tool_name="calc",
        arguments={"a": "not-a-number", "operation": "add"},
    )
    bad_result = await executor.execute(invalid_call)
    assert bad_result.success is False
    assert bad_result.error is not None
    assert bad_result.error["code"] == ToolErrorCode.VALIDATION_ERROR.value
    assert "validation_errors" in bad_result.error["details"]


@pytest.mark.asyncio
async def test_tool_output_validation():
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    # Tool whose handler violates the declared output_schema
    @registry.tool(
        name="bad_output_tool",
        description="Returns invalid schema",
        input_schema=CalculatorInput,
        output_schema=CalculatorOutput,
    )
    async def bad_output_tool(a: float, b: float, operation: str) -> dict[str, Any]:
        # Missing required 'result' float field in output
        return {"wrong_key": "some_value"}

    call = ToolCall(
        tool_name="bad_output_tool",
        arguments={"a": 1.0, "b": 2.0, "operation": "add"},
    )
    result = await executor.execute(call)
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == ToolErrorCode.VALIDATION_ERROR.value
    assert "validation_errors" in bad_result_keys(result)


def bad_result_keys(result: Any) -> list[str]:
    return list(result.error.get("details", {}).keys())


@pytest.mark.asyncio
async def test_permission_level_enforcement():
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    @registry.tool(
        name="delete_account",
        description="High sensitivity account deletion",
        input_schema=SensitiveInput,
        permission_level=ToolPermissionLevel.ADMIN,
    )
    async def delete_account(resource_id: str, action: str) -> str:
        return f"Deleted {resource_id}"

    # 1. Caller with STANDARD permission attempts ADMIN tool -> Rejected
    unauthorized_call = ToolCall(
        tool_name="delete_account",
        arguments={"resource_id": "acc-123", "action": "delete"},
        caller_permission_level=ToolPermissionLevel.STANDARD,
    )
    denied = await executor.execute(unauthorized_call)
    assert denied.success is False
    assert denied.error is not None
    assert denied.error["code"] == ToolErrorCode.PERMISSION_DENIED.value

    # 2. Caller with ADMIN permission -> Allowed
    authorized_call = ToolCall(
        tool_name="delete_account",
        arguments={"resource_id": "acc-123", "action": "delete"},
        caller_permission_level=ToolPermissionLevel.ADMIN,
    )
    allowed = await executor.execute(authorized_call)
    assert allowed.success is True
    assert allowed.data == "Deleted acc-123"


@pytest.mark.asyncio
async def test_tool_timeout_handling():
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    @registry.tool(
        name="sleepy_tool",
        description="Slow execution tool",
        input_schema=CalculatorInput,
        timeout=0.1,  # 100ms timeout
        retry_policy=RetryPolicy(max_retries=0),
    )
    async def sleepy_tool(a: float, b: float, operation: str) -> float:
        await asyncio.sleep(0.5)
        return a + b

    call = ToolCall(
        tool_name="sleepy_tool",
        arguments={"a": 1.0, "b": 1.0, "operation": "add"},
    )
    timed_out = await executor.execute(call)
    assert timed_out.success is False
    assert timed_out.error is not None
    assert timed_out.error["code"] == ToolErrorCode.TIMEOUT_ERROR.value
    assert timed_out.execution_time_ms >= 90.0


@pytest.mark.asyncio
async def test_tool_retry_on_transient_failure():
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    attempt_counter = 0

    @registry.tool(
        name="flaky_network_call",
        description="Fails initially then succeeds",
        input_schema=CalculatorInput,
        retry_policy=RetryPolicy(
            max_retries=2,
            initial_delay_seconds=0.01,
            retryable_error_types=["ConnectionError"],
        ),
    )
    async def flaky_call(a: float, b: float, operation: str) -> float:
        nonlocal attempt_counter
        attempt_counter += 1
        if attempt_counter == 1:
            raise ConnectionError("Transient network glitch")
        return a + b

    call = ToolCall(
        tool_name="flaky_network_call",
        arguments={"a": 5.0, "b": 5.0, "operation": "add"},
    )
    result = await executor.execute(call)
    assert result.success is True
    assert result.data == 10.0
    assert result.retries_attempted == 1
    assert attempt_counter == 2


@pytest.mark.asyncio
async def test_tool_retry_exhaustion():
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    @registry.tool(
        name="persistently_failing",
        description="Always fails",
        input_schema=CalculatorInput,
        retry_policy=RetryPolicy(
            max_retries=2,
            initial_delay_seconds=0.01,
            retryable_error_types=["ConnectionError"],
        ),
    )
    async def always_fails(a: float, b: float, operation: str) -> float:
        raise ConnectionError("Permanent host unreachable")

    call = ToolCall(
        tool_name="persistently_failing",
        arguments={"a": 1.0, "b": 2.0, "operation": "add"},
    )
    result = await executor.execute(call)
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == ToolErrorCode.EXECUTION_FAILED.value
    assert result.retries_attempted == 2


@pytest.mark.asyncio
async def test_tool_cancellation_support():
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    @registry.tool(
        name="dummy_tool",
        description="Dummy action",
        input_schema=CalculatorInput,
    )
    async def dummy(a: float, b: float, operation: str) -> float:
        return a + b

    token = CancellationToken()
    token.cancel(reason="Execution aborted by user request")

    call = ToolCall(
        tool_name="dummy_tool",
        arguments={"a": 1.0, "b": 2.0, "operation": "add"},
    )
    result = await executor.execute(call, cancellation_token=token)
    assert result.success is False
    assert result.error is not None
    assert result.error["code"] == ToolErrorCode.CANCELLED.value


# ============================================================================
# INTEGRATION: AGENT RUNTIME WITH GENERIC TOOL ADAPTER
# ============================================================================


class MockStatePort(StateRetrievalPort):
    def __init__(self) -> None:
        self.states: dict[str, AgentState] = {}

    async def get_state(self, goal_id: str, user_id: str) -> AgentState:
        return self.states.get(f"{goal_id}:{user_id}", AgentState(goal_id=goal_id, user_id=user_id))

    async def update_state(self, run_id: str, state: AgentState) -> None:
        self.states[f"{state.goal_id}:{state.user_id}"] = state


class MockEvalPort(EvaluationPort):
    async def evaluate_step(self, step: AgentStep, current_state: AgentState) -> StepEvaluation:
        return StepEvaluation(
            is_successful=step.action_result.success if step.action_result else True,
            progress_made=True,
            is_terminal=False,
            evaluation_notes="Step evaluated successfully",
        )


class MockMemoryPort(MemoryPort):
    async def retrieve_context(
        self, query: str, user_id: str, goal_id: str
    ) -> list[dict[str, Any]]:
        return []

    async def record_interaction(self, run_id: str, step: AgentStep) -> None:
        pass


@pytest.mark.asyncio
async def test_agent_executes_registered_tool_end_to_end():
    """Acceptance Criteria: Agent safely discovers and executes registered mock tools via adapter."""
    # 1. Setup tool registry with a registered mock calculator tool
    registry = ToolRegistry()

    @registry.tool(
        name="compute_metrics",
        description="Compute statistical metrics",
        input_schema=CalculatorInput,
        output_schema=CalculatorOutput,
        permission_level=ToolPermissionLevel.STANDARD,
    )
    async def compute_metrics(a: float, b: float, operation: str) -> dict[str, Any]:
        return {"result": a * b, "operation": operation}

    # 2. Setup GenericToolExecutionAdapter
    tool_adapter = GenericToolExecutionAdapter(
        registry=registry,
        default_caller_permission=ToolPermissionLevel.STANDARD,
    )

    # Verify agent sees the tool in available tools
    available = await tool_adapter.get_available_tools()
    assert "compute_metrics" in available

    # 3. Setup agent runtime with deterministic policy calling this tool
    policy = DeterministicSequencePolicy(
        [
            AgentDecision(
                decision_type=DecisionType.CALL_TOOL,
                tool_name="compute_metrics",
                tool_args={"a": 6.0, "b": 7.0, "operation": "multiply"},
                reasoning="Compute product of metrics",
            ),
            AgentDecision(
                decision_type=DecisionType.FINISH,
                reasoning="Calculation done, concluding run",
            ),
        ]
    )

    state_port = MockStatePort()
    eval_port = MockEvalPort()
    memory_port = MockMemoryPort()

    runtime = AgentRuntime(
        state_port=state_port,
        tool_port=tool_adapter,
        eval_port=eval_port,
        memory_port=memory_port,
        decision_policy=policy,
        max_iterations=5,
    )

    orchestrator = AgentOrchestrator()
    run = orchestrator.create_run(goal_id="goal-e2e-tool-01", user_id="user-01")

    completed_run = await orchestrator.execute_run(run=run, runtime=runtime)

    # 4. Verify end-to-end outcome
    assert completed_run.status == AgentStatus.COMPLETED
    assert completed_run.error is None
    assert completed_run.iteration_count == 2

    # Verify tool execution outcome recorded in state variables
    assert "tool_result_compute_metrics_1" in completed_run.state.variables
    tool_output = completed_run.state.variables["tool_result_compute_metrics_1"]
    assert tool_output == {"result": 42.0, "operation": "multiply"}

    # Verify step traces recorded
    act_step = next(s for s in completed_run.steps if s.phase.value == "act")
    assert act_step.action_result is not None
    assert act_step.action_result.success is True
    assert act_step.action_result.result == {"result": 42.0, "operation": "multiply"}
