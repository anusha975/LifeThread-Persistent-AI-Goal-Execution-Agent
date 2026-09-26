import asyncio
import logging
import random
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.services.aws.config import AWSConfigManager
from app.services.aws.cost_tracker import cost_tracker
from app.services.llm.mock import MockLLMProvider
from app.services.llm.provider import BaseLLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger("lifethread.aws.bedrock")


class BedrockLLMProvider(BaseLLMProvider):
    """Amazon Bedrock LLM Provider conforming to BaseLLMProvider interface.

    Leverages Amazon Bedrock Converse API with:
    - Enterprise model routing (Claude 3.5 Sonnet for deep reasoning vs Claude 3 Haiku for speed/cost)
    - Botocore adaptive retry policies & exponential backoff with jitter
    - Real-time token usage and cost accounting
    - Graceful fallback to local mock/fallback provider when AWS is unreachable or unconfigured
    """

    def __init__(
        self,
        default_model: str | None = None,
        fast_model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        fallback_provider: BaseLLMProvider | None = None,
    ) -> None:
        settings = get_settings()
        self.default_model = default_model or settings.AWS_BEDROCK_DEFAULT_MODEL
        self.fast_model = fast_model or settings.AWS_BEDROCK_FAST_MODEL
        self.timeout = timeout or settings.AWS_BEDROCK_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else settings.AWS_BEDROCK_MAX_RETRIES
        self.fallback_on_error = settings.AWS_BEDROCK_FALLBACK_ON_ERROR
        self.fallback_provider = fallback_provider or MockLLMProvider()

    def _get_client(self) -> Any:
        return AWSConfigManager.get_client(
            service_name="bedrock-runtime",
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    def select_model(self, model: str | None = None, fast: bool = False) -> str:
        """Route to appropriate model based on requested tier or explicit model ID."""
        if model:
            return model
        if fast:
            return self.fast_model
        return self.default_model

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        fast: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a single completion using Bedrock Converse API."""
        messages = [LLMMessage(role="user", content=prompt)]
        return await self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            fast=fast,
            **kwargs,
        )

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        fast: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """Execute chat completion with Amazon Bedrock Converse API."""
        target_model = self.select_model(model, fast=fast)

        # Check if AWS credentials or environment appear available
        if not AWSConfigManager.is_aws_available():
            if self.fallback_on_error:
                logger.info(
                    "AWS credentials not detected; routing request through fallback provider (%s)",
                    type(self.fallback_provider).__name__,
                )
                fb_res = await self.fallback_provider.chat(
                    messages,
                    model=target_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                return LLMResponse(
                    content=fb_res.content,
                    provider="aws-bedrock-fallback",
                    model=target_model,
                    raw_response={"fallback": True, "reason": "No AWS credentials detected"},
                )
            raise RuntimeError("AWS Bedrock requires valid AWS credentials or IAM role.")

        # Convert normalized messages to Bedrock Converse format
        system_prompts: list[dict[str, str]] = []
        converse_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role.lower() == "system":
                system_prompts.append({"text": msg.content})
            else:
                role = "assistant" if msg.role.lower() in ("assistant", "ai") else "user"
                converse_messages.append({
                    "role": role,
                    "content": [{"text": msg.content}],
                })

        # Ensure there is at least one user message
        if not converse_messages:
            converse_messages.append({"role": "user", "content": [{"text": "Hello"}]})

        inference_config: dict[str, Any] = {
            "temperature": max(0.0, min(1.0, temperature)),
        }
        if max_tokens:
            inference_config["maxTokens"] = max_tokens

        converse_params: dict[str, Any] = {
            "modelId": target_model,
            "messages": converse_messages,
            "inferenceConfig": inference_config,
        }
        if system_prompts:
            converse_params["system"] = system_prompts

        # Execute with exponential backoff and jitter for throttles
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                client = self._get_client()
                # Run sync boto3 call in thread pool to prevent blocking asyncio loop
                response = await asyncio.to_thread(client.converse, **converse_params)

                # Extract generated text
                output_message = response.get("output", {}).get("message", {})
                content_blocks = output_message.get("content", [])
                generated_text = "".join(
                    block.get("text", "") for block in content_blocks if "text" in block
                )

                # Extract token usage and record in cost tracker
                usage = response.get("usage", {})
                in_tokens = usage.get("inputTokens", 0)
                out_tokens = usage.get("outputTokens", 0)
                cost_tracker.record_invocation(
                    model_id=target_model,
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                )

                return LLMResponse(
                    content=generated_text,
                    provider="aws-bedrock",
                    model=target_model,
                    raw_response={
                        "stop_reason": response.get("stopReason"),
                        "metrics": response.get("metrics"),
                        "usage": usage,
                    },
                )

            except (ClientError, BotoCoreError, Exception) as exc:
                last_error = exc
                error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
                logger.warning(
                    "Bedrock converse attempt %d/%d failed with %s: %s",
                    attempt,
                    self.max_retries,
                    error_code,
                    exc,
                )

                # Exponential backoff with jitter on throttling or transient errors
                if attempt < self.max_retries:
                    backoff = (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                    await asyncio.sleep(backoff)

        # All retries exhausted
        if self.fallback_on_error:
            logger.error(
                "All Bedrock attempts failed (%s); engaging fallback provider (%s)",
                last_error,
                type(self.fallback_provider).__name__,
            )
            fb_res = await self.fallback_provider.chat(
                messages,
                model=target_model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            return LLMResponse(
                content=fb_res.content,
                provider="aws-bedrock-fallback",
                model=target_model,
                raw_response={
                    "fallback": True,
                    "error": str(last_error),
                },
            )

        raise RuntimeError(f"Bedrock invocation failed after {self.max_retries} retries: {last_error}") from last_error
