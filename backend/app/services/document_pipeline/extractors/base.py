from abc import ABC, abstractmethod
from typing import Any


class BaseExtractor(ABC):
    """Abstract base extractor interface for document formats."""

    @abstractmethod
    def extract(self, content: bytes, filename: str) -> tuple[str, dict[str, Any]]:
        """Extract text and metadata from raw document bytes.

        Returns:
            tuple[str, dict[str, Any]]: Extracted text content and document metadata.

        Raises:
            DocumentExtractionError: If text cannot be parsed or file is corrupt.
        """
        ...
