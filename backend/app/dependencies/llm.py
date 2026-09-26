from collections.abc import Generator

from app.services.llm import BaseLLMProvider, get_llm_provider


def get_llm_provider_dep() -> Generator[BaseLLMProvider, None, None]:
    """FastAPI dependency yielding an LLMProvider instance."""
    provider = get_llm_provider()
    yield provider
