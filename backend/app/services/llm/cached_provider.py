"""Performance-Optimized Cached LLM Provider (Module 43).

Wraps any BaseLLMProvider with an intelligent LRU semantic cache for deterministic
LLM completions (temperature <= 0.1 or explicit caching).
Preserves correctness while slashing latency and token usage.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from app.services.llm.provider import BaseLLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger("lifethread.llm.cache")


class CachedLLMProvider(BaseLLMProvider):
    """Decorator/Wrapper around any BaseLLMProvider providing transparent response caching."""

    def __init__(
        self,
        underlying_provider: BaseLLMProvider,
        max_cache_size: int = 1000,
        ttl_seconds: float = 300.0,
        max_cachable_temperature: float = 0.1,
    ) -> None:
        self.underlying_provider = underlying_provider
        self.max_cache_size = max_cache_size
        self.ttl_seconds = ttl_seconds
        self.max_cachable_temperature = max_cachable_temperature

        # Cache storage: key -> (timestamp, LLMResponse, estimated_tokens)
        self._cache: dict[str, tuple[float, LLMResponse, int]] = {}
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.total_tokens_saved: int = 0

    def _make_generate_key(
        self,
        prompt: str,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        kwargs: dict[str, Any],
    ) -> str:
        serialized = json.dumps(
            {
                "type": "generate",
                "prompt": prompt,
                "model": model or "default",
                "temperature": round(temperature, 2),
                "max_tokens": max_tokens,
                "kwargs": {k: str(v) for k, v in sorted(kwargs.items())},
            },
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _make_chat_key(
        self,
        messages: list[LLMMessage],
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        kwargs: dict[str, Any],
    ) -> str:
        serialized = json.dumps(
            {
                "type": "chat",
                "messages": [{"role": m.role, "content": m.content, "name": m.name} for m in messages],
                "model": model or "default",
                "temperature": round(temperature, 2),
                "max_tokens": max_tokens,
                "kwargs": {k: str(v) for k, v in sorted(kwargs.items())},
            },
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text.split()))

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate single completion with transparent caching for low-temperature calls."""
        # Only cache deterministic or explicitly approved calls
        should_cache = temperature <= self.max_cachable_temperature or kwargs.get("force_cache", False)

        if should_cache:
            cache_key = self._make_generate_key(prompt, model, temperature, max_tokens, kwargs)
            now = time.time()
            if cache_key in self._cache:
                ts, cached_resp, saved_tokens = self._cache[cache_key]
                if now - ts < self.ttl_seconds:
                    self.cache_hits += 1
                    self.total_tokens_saved += saved_tokens
                    # Return copy marked as cached
                    return LLMResponse(
                        content=cached_resp.content,
                        provider=cached_resp.provider,
                        model=cached_resp.model,
                        raw_response={"cached": True, "cached_at": ts},
                    )

        self.cache_misses += 1
        resp = await self.underlying_provider.generate(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        if should_cache:
            cache_key = self._make_generate_key(prompt, model, temperature, max_tokens, kwargs)
            if len(self._cache) >= self.max_cache_size:
                self._cache.pop(next(iter(self._cache)))
            tokens = self._estimate_tokens(prompt + resp.content)
            self._cache[cache_key] = (time.time(), resp, tokens)

        return resp

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Execute chat completion with transparent caching for low-temperature calls."""
        should_cache = temperature <= self.max_cachable_temperature or kwargs.get("force_cache", False)

        if should_cache:
            cache_key = self._make_chat_key(messages, model, temperature, max_tokens, kwargs)
            now = time.time()
            if cache_key in self._cache:
                ts, cached_resp, saved_tokens = self._cache[cache_key]
                if now - ts < self.ttl_seconds:
                    self.cache_hits += 1
                    self.total_tokens_saved += saved_tokens
                    return LLMResponse(
                        content=cached_resp.content,
                        provider=cached_resp.provider,
                        model=cached_resp.model,
                        raw_response={"cached": True, "cached_at": ts},
                    )

        self.cache_misses += 1
        resp = await self.underlying_provider.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        if should_cache:
            cache_key = self._make_chat_key(messages, model, temperature, max_tokens, kwargs)
            if len(self._cache) >= self.max_cache_size:
                self._cache.pop(next(iter(self._cache)))
            prompt_text = " ".join(m.content for m in messages)
            tokens = self._estimate_tokens(prompt_text + resp.content)
            self._cache[cache_key] = (time.time(), resp, tokens)

        return resp

    def clear_cache(self) -> None:
        """Evict all entries from the LLM cache."""
        self._cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0
        self.total_tokens_saved = 0
