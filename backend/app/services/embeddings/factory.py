import os

from app.core.config import get_settings
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.mock import MockEmbeddingProvider
from app.services.embeddings.openai import OpenAIEmbeddingProvider

_global_provider: BaseEmbeddingProvider | None = None


def set_global_embedding_provider(provider: BaseEmbeddingProvider | None) -> None:
    """Explicitly set or override the active global embedding provider (useful for tests)."""
    global _global_provider
    _global_provider = provider


def get_embedding_provider(provider_type: str | None = None) -> BaseEmbeddingProvider:
    """Resolve and return the appropriate embedding provider based on config or override."""
    global _global_provider
    if _global_provider is not None:
        return _global_provider

    settings = get_settings()
    ptype = (
        provider_type
        or getattr(settings, "EMBEDDING_PROVIDER", None)
        or os.getenv("EMBEDDING_PROVIDER", "mock")
    ).lower()

    if ptype == "openai":
        api_key = settings.OPENAI_API_KEY
        if api_key and api_key != "CHANGEME_IN_PRODUCTION":
            return OpenAIEmbeddingProvider(api_key=api_key)

    # Default to deterministic MockEmbeddingProvider
    return MockEmbeddingProvider(dimension=1536)
