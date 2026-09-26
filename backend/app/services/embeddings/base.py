from abc import ABC, abstractmethod


class EmbeddingGenerationError(Exception):
    """Exception raised when vector embedding generation fails."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error
        self.message = message


class BaseEmbeddingProvider(ABC):
    """Abstract base class for semantic vector embedding providers."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the vector dimensionality (e.g. 1536)."""
        ...

    @abstractmethod
    async def generate_embedding(self, text: str) -> list[float]:
        """Generate a single normalized vector embedding for the provided text.

        Raises:
            EmbeddingGenerationError: If embedding generation fails.
        """
        ...

    @abstractmethod
    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a batch of texts.

        Raises:
            EmbeddingGenerationError: If embedding generation fails.
        """
        ...
