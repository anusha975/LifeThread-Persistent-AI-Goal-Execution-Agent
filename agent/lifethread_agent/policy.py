from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from lifethread_agent.models import AgentDecision, AgentState, AgentStep
from lifethread_agent.types import DecisionType


class DecisionPolicyPort(ABC):
    """Abstract port for agent decision-making policies (rule-based, heuristic, or LLM-driven)."""

    @abstractmethod
    async def decide(
        self,
        state: AgentState,
        available_tools: list[str],
        recent_steps: list[AgentStep],
    ) -> AgentDecision:
        """Formulate a structured decision given current state, available tools, and history."""
        pass


class DeterministicSequencePolicy(DecisionPolicyPort):
    """Deterministic policy that yields a fixed sequence of decisions.

    Useful for controlled integration runs, test fixtures, and scripted workflows.
    """

    def __init__(self, decisions: list[AgentDecision]) -> None:
        self.decisions = list(decisions)
        self.cursor = 0

    async def decide(
        self,
        state: AgentState,
        available_tools: list[str],
        recent_steps: list[AgentStep],
    ) -> AgentDecision:
        if self.cursor < len(self.decisions):
            decision = self.decisions[self.cursor]
            self.cursor += 1
            return decision

        # Default fallback when sequence finishes
        return AgentDecision(
            decision_type=DecisionType.FINISH,
            reasoning="Deterministic decision sequence exhausted, concluding execution.",
        )


class DynamicRulePolicy(DecisionPolicyPort):
    """Policy delegating decisions to a dynamic callable rule."""

    def __init__(
        self,
        rule_func: Callable[[AgentState, list[str], list[AgentStep]], AgentDecision],
    ) -> None:
        self.rule_func = rule_func

    async def decide(
        self,
        state: AgentState,
        available_tools: list[str],
        recent_steps: list[AgentStep],
    ) -> AgentDecision:
        return self.rule_func(state, available_tools, recent_steps)


class MockToolPolicy(DecisionPolicyPort):
    """Convenience policy that executes a tool N times and then finishes."""

    def __init__(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        max_tool_calls: int = 1,
    ) -> None:
        self.tool_name = tool_name
        self.tool_args = tool_args or {}
        self.max_tool_calls = max_tool_calls
        self.calls_made = 0

    async def decide(
        self,
        state: AgentState,
        available_tools: list[str],
        recent_steps: list[AgentStep],
    ) -> AgentDecision:
        if self.calls_made < self.max_tool_calls:
            self.calls_made += 1
            return AgentDecision(
                decision_type=DecisionType.CALL_TOOL,
                tool_name=self.tool_name,
                tool_args=self.tool_args,
                reasoning=f"Executing tool {self.tool_name} (call {self.calls_made}/{self.max_tool_calls})",
            )
        return AgentDecision(
            decision_type=DecisionType.FINISH,
            reasoning=f"Completed {self.calls_made} planned tool calls.",
        )
