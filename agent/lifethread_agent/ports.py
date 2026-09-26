from abc import ABC, abstractmethod
from typing import Any

from lifethread_agent.models import (
    AgentState,
    AgentStep,
    StepEvaluation,
    ToolExecutionResult,
)


class StateRetrievalPort(ABC):
    """Abstract port for querying and updating agent domain state.

    Decouples the agent orchestrator from database, ORM, or cache implementations.
    """

    @abstractmethod
    async def get_state(self, goal_id: str, user_id: str) -> AgentState:
        """Retrieve current domain state for a given goal and user."""
        pass

    @abstractmethod
    async def update_state(self, run_id: str, state: AgentState) -> None:
        """Persist or broadcast state update for an active agent run."""
        pass


class ToolExecutionPort(ABC):
    """Abstract port for inspecting and invoking approved agent tools."""

    @abstractmethod
    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> ToolExecutionResult:
        """Execute an approved tool and return a structured ToolExecutionResult."""
        pass

    @abstractmethod
    async def get_available_tools(self) -> list[str]:
        """Return the catalog of approved tool names available to this agent."""
        pass


class EvaluationPort(ABC):
    """Abstract port for assessing agent step progress and determining completion."""

    @abstractmethod
    async def evaluate_step(
        self,
        step: AgentStep,
        current_state: AgentState,
    ) -> StepEvaluation:
        """Evaluate the effect of an executed step and recommend subsequent behavior."""
        pass


class MemoryPort(ABC):
    """Abstract port for long-term and working memory retrieval and persistence."""

    @abstractmethod
    async def retrieve_context(
        self,
        query: str,
        user_id: str,
        goal_id: str,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant historical context or semantic memories."""
        pass

    @abstractmethod
    async def record_interaction(
        self,
        run_id: str,
        step: AgentStep,
    ) -> None:
        """Record an execution step into memory storage for future recall."""
        pass
