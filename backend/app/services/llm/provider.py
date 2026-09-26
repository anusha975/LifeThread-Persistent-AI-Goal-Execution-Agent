from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """Normalized message representation across LLM providers."""

    role: str = Field(..., description="Role of the author: system, user, assistant, or tool")
    content: str = Field(..., description="Text content of the message")
    name: str | None = Field(default=None, description="Optional name of the sender or function")


class LLMResponse(BaseModel):
    """Normalized response representation returned by LLM providers."""

    content: str = Field(..., description="Generated text response")
    provider: str = Field(..., description="Identifier of the provider fulfilling the request")
    model: str = Field(..., description="Model version or tag used for generation")
    raw_response: dict[str, Any] | None = Field(
        default=None,
        description="Provider-specific raw response payload for debugging and audit logs",
    )


class BaseLLMProvider(ABC):
    """Abstract interface defining the contract for LLM providers.

    Concrete adapters (e.g. OpenAI, Anthropic, Local) implement this contract,
    allowing provider swapping without touching agent or application code.
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a single completion for the given prompt."""
        pass

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Execute a conversational completion with message history."""
        pass


# Explicit alias for domain naming convention required by LifeThread specifications
LLMProvider = BaseLLMProvider
