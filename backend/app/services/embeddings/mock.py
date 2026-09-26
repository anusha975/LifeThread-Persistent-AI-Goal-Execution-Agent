import hashlib
import math

from app.services.embeddings.base import BaseEmbeddingProvider, EmbeddingGenerationError


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic, mock embedding provider for tests and local development.

    Produces unit-normalized vectors where dot product equals cosine similarity.
    Supports fixed vector registrations and failure simulations.
    """

    def __init__(
        self,
        dimension: int = 1536,
        fail_always: bool = False,
        fail_on_substrings: list[str] | None = None,
    ) -> None:
        self._dimension = dimension
        self.fail_always = fail_always
        self.fail_on_substrings = fail_on_substrings or []
        self._preset_vectors: dict[str, list[float]] = {}

    @property
    def dimension(self) -> int:
        return self._dimension

    def set_embedding(self, text: str, vector: list[float]) -> None:
        """Register a fixed embedding vector for an exact text input."""
        if len(vector) != self._dimension:
            raise ValueError(
                f"Vector dimension mismatch: expected {self._dimension}, got {len(vector)}"
            )
        # Normalize the preset vector to unit length
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0:
            self._preset_vectors[text] = [x / norm for x in vector]
        else:
            self._preset_vectors[text] = vector

    def _should_fail(self, text: str) -> bool:
        if self.fail_always:
            return True
        for sub in self.fail_on_substrings:
            if sub in text:
                return True
        return False

    def _generate_deterministic_vector(self, text: str) -> list[float]:
        """Compute a deterministic pseudo-random unit vector using SHA-256 seed."""
        # Use SHA-256 hash of the text to seed a deterministic sequence
        seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        seed_int = int.from_bytes(seed_bytes, byteorder="big")

        raw_vector: list[float] = []
        current_state = seed_int

        # Linear Congruential Generator (LCG) for deterministic pseudo-random generation
        for _ in range(self._dimension):
            current_state = (current_state * 6364136223846793005 + 1442695040888963407) & (
                (1 << 64) - 1
            )
            # Map 64-bit uint to float between -1.0 and 1.0
            val = ((current_state / (1 << 64)) * 2.0) - 1.0
            raw_vector.append(val)

        # Normalize to unit length (L2 norm = 1.0)
        norm = math.sqrt(sum(x * x for x in raw_vector))
        if norm == 0.0:
            norm = 1.0
        return [round(x / norm, 6) for x in raw_vector]

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate a single embedding vector."""
        if self._should_fail(text):
            raise EmbeddingGenerationError(
                f"Mock embedding provider simulated failure for text: '{text[:30]}...'"
            )

        if text in self._preset_vectors:
            return list(self._preset_vectors[text])

        return self._generate_deterministic_vector(text)

    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate batch embeddings."""
        return [await self.generate_embedding(t) for t in texts]
