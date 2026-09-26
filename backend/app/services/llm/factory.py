from app.core.config import get_settings
from app.services.llm.mock import MockLLMProvider
from app.services.llm.openai import OpenAILLMProvider
from app.services.llm.provider import BaseLLMProvider


class LLMProviderRegistry:
    """Registry and factory for LLM providers."""

    _providers: dict[str, type[BaseLLMProvider]] = {
        "mock": MockLLMProvider,
        "openai": OpenAILLMProvider,
    }

    @classmethod
    def register(cls, name: str, provider_cls: type[BaseLLMProvider]) -> None:
        """Register a new LLM provider implementation."""
        cls._providers[name.lower()] = provider_cls

    @classmethod
    def get(cls, name: str | None = None) -> BaseLLMProvider:
        """Instantiate an LLM provider by name or fallback to settings."""
        settings = get_settings()
        provider_name = (name or settings.LLM_PROVIDER).lower()

        if provider_name == "openai":
            return OpenAILLMProvider(api_key=settings.OPENAI_API_KEY)
        elif provider_name in ("bedrock", "aws", "aws-bedrock"):
            from app.services.aws.bedrock_provider import BedrockLLMProvider

            return BedrockLLMProvider()

        provider_cls = cls._providers.get(provider_name, MockLLMProvider)
        return provider_cls()

    @classmethod
    def get_cached(
        cls,
        name: str | None = None,
        max_cache_size: int = 1000,
        ttl_seconds: float = 300.0,
    ) -> BaseLLMProvider:
        """Instantiate an LLM provider wrapped with an LRU cache."""
        from app.services.llm.cached_provider import CachedLLMProvider

        base = cls.get(name)
        return CachedLLMProvider(
            underlying_provider=base,
            max_cache_size=max_cache_size,
            ttl_seconds=ttl_seconds,
        )


def get_llm_provider(name: str | None = None, cached: bool = False) -> BaseLLMProvider:
    """Convenience helper to retrieve an LLM provider instance, optionally cached."""
    if cached:
        return LLMProviderRegistry.get_cached(name)
    return LLMProviderRegistry.get(name)
