from collections.abc import Callable
from typing import Any

from app.services.llm.provider import BaseLLMProvider, LLMMessage, LLMResponse


class MockLLMProvider(BaseLLMProvider):
    """Deterministic, mock LLM provider for unit/integration testing and offline development."""

    def __init__(
        self,
        default_response: str = "{}",
        responses: list[str] | None = None,
        custom_handler: Callable[..., str | LLMResponse] | None = None,
    ) -> None:
        self.default_response = default_response
        self._response_queue: list[str] = list(responses) if responses else []
        self._custom_handler = custom_handler
        self.call_history: list[dict[str, Any]] = []

    def set_response(self, content: str) -> None:
        """Set a single default response string."""
        self.default_response = content

    def set_responses(self, contents: list[str]) -> None:
        """Enqueue a sequence of responses to be consumed sequentially."""
        self._response_queue = list(contents)

    def clear_history(self) -> None:
        """Reset the call history."""
        self.call_history.clear()

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a deterministic completion based on queued or default responses."""
        record = {
            "type": "generate",
            "prompt": prompt,
            "model": model or "mock-model",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "kwargs": kwargs,
        }
        self.call_history.append(record)

        if self._custom_handler is not None:
            handled = self._custom_handler(prompt=prompt, model=model, **kwargs)
            if isinstance(handled, LLMResponse):
                return handled
            return LLMResponse(content=str(handled), provider="mock", model=model or "mock-model")

        if self._response_queue:
            content = self._response_queue.pop(0)
        else:
            content = self.default_response

        return LLMResponse(
            content=content,
            provider="mock",
            model=model or "mock-model",
            raw_response={"status": "mocked", "call_count": len(self.call_history)},
        )

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Execute a conversational completion with mock response."""
        record = {
            "type": "chat",
            "messages": [m.model_dump() for m in messages],
            "model": model or "mock-model",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "kwargs": kwargs,
        }
        self.call_history.append(record)

        last_content = messages[-1].content if messages else ""
        if self._custom_handler is not None:
            handled = self._custom_handler(
                messages=messages, prompt=last_content, model=model, **kwargs
            )
            if isinstance(handled, LLMResponse):
                return handled
            return LLMResponse(content=str(handled), provider="mock", model=model or "mock-model")

        if self._response_queue:
            content = self._response_queue.pop(0)
        else:
            content = self.default_response

        return LLMResponse(
            content=content,
            provider="mock",
            model=model or "mock-model",
            raw_response={"status": "mocked", "call_count": len(self.call_history)},
        )
