from typing import Any

from app.services.document_pipeline.errors import DocumentExtractionError
from app.services.document_pipeline.extractors.base import BaseExtractor


class TextExtractor(BaseExtractor):
    """Extractor for plain text documents."""

    def extract(self, content: bytes, filename: str) -> tuple[str, dict[str, Any]]:
        # Attempt UTF-8, then Latin-1, then cp1252
        text: str | None = None
        encoding_used = "utf-8"

        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                text = content.decode(enc)
                encoding_used = enc
                break
            except UnicodeDecodeError:
                continue

        if text is None:
            raise DocumentExtractionError(
                f"Failed to decode text file '{filename}': Unsupported character encoding."
            )

        metadata: dict[str, Any] = {
            "format": "txt",
            "encoding": encoding_used,
            "raw_char_count": len(text),
            "line_count": text.count("\n") + 1,
        }
        return text, metadata
