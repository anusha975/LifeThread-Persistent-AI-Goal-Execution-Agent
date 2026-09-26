import logging
from typing import Any

import httpx

from app.services.embeddings.base import BaseEmbeddingProvider, EmbeddingGenerationError

logger = logging.getLogger("lifethread.embeddings.openai")


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI API vector embedding provider."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._dimension = dimension
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def dimension(self) -> int:
        return self._dimension

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate a single embedding via OpenAI API."""
        embeddings = await self.generate_embeddings([text])
        if not embeddings:
            raise EmbeddingGenerationError("OpenAI returned empty embedding list")
        return embeddings[0]

    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate batch embeddings via OpenAI API."""
        if not texts:
            return []

        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
            "dimensions": self._dimension,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code != 200:
                    error_msg = f"OpenAI embedding API failed with status {response.status_code}: {response.text}"
                    logger.error(error_msg)
                    raise EmbeddingGenerationError(error_msg)

                data = response.json()
                sorted_data = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
                return [item["embedding"] for item in sorted_data]
        except EmbeddingGenerationError:
            raise
        except Exception as e:
            error_msg = f"Network or execution error calling OpenAI embeddings: {e!s}"
            logger.error(error_msg)
            raise EmbeddingGenerationError(error_msg, original_error=e) from e
