from app.services.document_pipeline.errors import DocumentValidationError
from app.services.document_pipeline.extractors.base import BaseExtractor
from app.services.document_pipeline.extractors.markdown_extractor import MarkdownExtractor
from app.services.document_pipeline.extractors.pdf_extractor import PdfExtractor
from app.services.document_pipeline.extractors.text_extractor import TextExtractor

_EXTRACTORS: dict[str, BaseExtractor] = {
    "application/pdf": PdfExtractor(),
    "text/plain": TextExtractor(),
    "text/markdown": MarkdownExtractor(),
    "text/x-markdown": MarkdownExtractor(),
}


def get_extractor(content_type: str) -> BaseExtractor:
    """Resolve and return appropriate extractor instance for the given MIME type."""
    normalized_type = content_type.lower().split(";")[0].strip()
    extractor = _EXTRACTORS.get(normalized_type)
    if not extractor:
        supported = ", ".join(_EXTRACTORS.keys())
        raise DocumentValidationError(
            f"No extractor registered for content type '{content_type}'. Supported: {supported}"
        )
    return extractor
