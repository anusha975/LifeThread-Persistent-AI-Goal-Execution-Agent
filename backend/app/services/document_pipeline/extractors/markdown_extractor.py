import re
from typing import Any

from app.services.document_pipeline.errors import DocumentExtractionError
from app.services.document_pipeline.extractors.base import BaseExtractor


class MarkdownExtractor(BaseExtractor):
    """Extractor for Markdown documents preserving headers, code blocks, and structural elements."""

    def extract(self, content: bytes, filename: str) -> tuple[str, dict[str, Any]]:
        text: str | None = None
        encoding_used = "utf-8"

        for enc in ("utf-8", "latin-1"):
            try:
                text = content.decode(enc)
                encoding_used = enc
                break
            except UnicodeDecodeError:
                continue

        if text is None:
            raise DocumentExtractionError(
                f"Failed to decode markdown file '{filename}': Invalid character encoding."
            )

        # Inspect basic structural elements for rich metadata
        headings = re.findall(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE)
        code_blocks = len(re.findall(r"```", text)) // 2

        metadata: dict[str, Any] = {
            "format": "markdown",
            "encoding": encoding_used,
            "raw_char_count": len(text),
            "line_count": text.count("\n") + 1,
            "heading_count": len(headings),
            "code_block_count": code_blocks,
            "primary_heading": headings[0][1] if headings else None,
        }
        return text, metadata
