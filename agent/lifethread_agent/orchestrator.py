import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from lifethread_agent.models import AgentRun, AgentState
from lifethread_agent.runtime import AgentRuntime
from lifethread_agent.state_machine import CancellationToken
from lifethread_agent.types import AgentContext, AgentStatus, OrchestratorResult

logger = logging.getLogger("lifethread.agent.orchestrator")


class AgentOrchestrator:
    """Core Agent Orchestrator facade for LifeThread.

    Adheres strictly to Clean Architecture:
    - Zero database imports or direct I/O dependencies.
    - Manages AgentRun lifecycles via injected AgentRuntime and abstract service ports.
    """

    def __init__(self, orchestrator_id: str | None = None) -> None:
        self.orchestrator_id = orchestrator_id or "default-orchestrator"
        logger.info(f"Initialized AgentOrchestrator [{self.orchestrator_id}]")

    def create_run(
        self,
        goal_id: str,
        user_id: str,
        initial_context: dict[str, Any] | None = None,
        initial_variables: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> AgentRun:
        """Instantiate a new unstarted AgentRun with initialized domain state."""
        run_identifier = run_id or str(uuid.uuid4())
        initial_state = AgentState(
            goal_id=goal_id,
            user_id=user_id,
            context=initial_context or {},
            variables=initial_variables or {},
        )

        run = AgentRun(
            run_id=run_identifier,
            goal_id=goal_id,
            user_id=user_id,
            status=AgentStatus.PENDING,
            state=initial_state,
        )
        logger.info(f"Created AgentRun [{run.run_id}] for goal [{goal_id}]")
        return run

    async def execute_run(
        self,
        run: AgentRun,
        runtime: AgentRuntime,
        cancellation_token: CancellationToken | None = None,
    ) -> AgentRun:
        """Launch execution loop of an AgentRun via the injected AgentRuntime."""
        logger.info(f"Orchestrator [{self.orchestrator_id}] executing run [{run.run_id}]")
        completed_run = await runtime.run(run=run, cancellation_token=cancellation_token)
        logger.info(
            f"Run [{run.run_id}] concluded with status [{completed_run.status}], "
            f"steps: {completed_run.current_step}, iterations: {completed_run.iteration_count}"
        )
        return completed_run

    async def initialize_run(self, context: AgentContext) -> OrchestratorResult:
        """Initialize an orchestration lifecycle pass for a given domain context.

        Maintains backward compatibility with earlier baseline tests.
        """
        logger.debug(
            f"Orchestrator {self.orchestrator_id} initializing run for goal {context.goal_id}"
        )
        user_id = getattr(context, "user_id", "default-user")
        run = self.create_run(
            goal_id=context.goal_id,
            user_id=user_id,
            initial_context=context.metadata,
        )
        run.started_at = datetime.now(UTC)

        return OrchestratorResult(
            status=AgentStatus.PENDING,
            step_count=0,
            summary=f"Run initialized for goal {context.goal_id}",
            run_id=run.run_id,
        )
