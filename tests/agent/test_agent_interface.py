import pytest
from lifethread_agent.orchestrator import AgentOrchestrator
from lifethread_agent.types import AgentContext, ExecutionStatus


@pytest.mark.asyncio
async def test_agent_orchestrator_initialization():
    orchestrator = AgentOrchestrator(orchestrator_id="test-orch-1")
    assert orchestrator.orchestrator_id == "test-orch-1"

    context = AgentContext(
        goal_id="goal-test-123",
        session_id="session-abc",
        metadata={"user_tier": "pro"},
    )
    assert context.goal_id == "goal-test-123"
    assert context.session_id == "session-abc"

    result = await orchestrator.initialize_run(context)
    assert result.status == ExecutionStatus.PENDING
    assert result.step_count == 0
    assert "goal-test-123" in (result.summary or "")
