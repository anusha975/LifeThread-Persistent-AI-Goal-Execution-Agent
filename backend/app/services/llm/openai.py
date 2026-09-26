import logging
from typing import Any

from app.services.llm.provider import BaseLLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger("lifethread.llm.openai")


class OpenAILLMProvider(BaseLLMProvider):
    """OpenAI API provider adapter conforming to BaseLLMProvider interface."""

    def __init__(self, api_key: str | None = None, default_model: str = "gpt-4o") -> None:
        self.api_key = api_key
        self.default_model = default_model

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion using OpenAI chat completion API."""
        messages = [LLMMessage(role="user", content=prompt)]
        return await self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
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
        """Execute chat completion with OpenAI."""
        target_model = model or self.default_model
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.api_key)
            formatted_messages = [{"role": m.role, "content": m.content} for m in messages]
            response = await client.chat.completions.create(
                model=target_model,
                messages=formatted_messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            choice = response.choices[0]
            content = choice.message.content or ""
            return LLMResponse(
                content=content,
                provider="openai",
                model=target_model,
                raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
            )
        except ImportError:
            logger.warning("openai package is not installed; falling back to stub response")
            return LLMResponse(
                content="[OpenAI provider requires 'openai' package]",
                provider="openai",
                model=target_model,
            )
