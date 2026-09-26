import io
import logging
from typing import Any

import pypdf

from app.services.document_pipeline.errors import DocumentExtractionError
from app.services.document_pipeline.extractors.base import BaseExtractor

logger = logging.getLogger("lifethread.pipeline.pdf_extractor")

MAX_PDF_PAGES = 500
MAX_EXTRACTED_CHARS = 20_000_000  # 20 MB text limit to prevent memory exhaustion bombs


class PdfExtractor(BaseExtractor):
    """Secure PDF text extractor utilizing pypdf with decompression bomb and corruption safeguards."""

    def extract(self, content: bytes, filename: str) -> tuple[str, dict[str, Any]]:
        stream = io.BytesIO(content)

        try:
            reader = pypdf.PdfReader(stream)
        except Exception as e:
            logger.error("Failed to parse PDF '%s': %s", filename, e)
            raise DocumentExtractionError(
                f"Failed to parse PDF document '{filename}': Invalid or corrupted PDF structure ({e!s})"
            ) from e

        # Check for encrypted or password-protected PDFs
        if reader.is_encrypted:
            try:
                # Attempt empty password decryption if possible
                decrypt_success = reader.decrypt("")
                if decrypt_success == 0:
                    raise DocumentExtractionError(
                        f"PDF document '{filename}' is password protected and cannot be extracted."
                    )
            except Exception as e:
                raise DocumentExtractionError(
                    f"PDF document '{filename}' is encrypted and password-protected: {e!s}"
                ) from e

        num_pages = len(reader.pages)
        if num_pages == 0:
            raise DocumentExtractionError(f"PDF document '{filename}' contains 0 pages.")

        if num_pages > MAX_PDF_PAGES:
            raise DocumentExtractionError(
                f"PDF document '{filename}' exceeds maximum allowed page count ({num_pages} > {MAX_PDF_PAGES})."
            )

        extracted_pages: list[str] = []
        total_chars = 0

        for page_idx, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception as e:
                logger.warning(
                    "Error extracting text from page %d of '%s': %s. Continuing with remaining pages.",
                    page_idx,
                    filename,
                    e,
                )
                page_text = ""

            total_chars += len(page_text)
            if total_chars > MAX_EXTRACTED_CHARS:
                raise DocumentExtractionError(
                    f"PDF document '{filename}' exceeded safe extraction text limit ({MAX_EXTRACTED_CHARS} chars)."
                )

            if page_text.strip():
                extracted_pages.append(page_text)

        full_text = "\n\n".join(extracted_pages)
        if not full_text.strip():
            logger.warning(
                "PDF '%s' has %d pages but yielded no extractable text.", filename, num_pages
            )

        # Extract PDF metadata safely
        pdf_meta = reader.metadata or {}
        doc_info: dict[str, Any] = {}
        for key in ("/Title", "/Author", "/Subject", "/Creator", "/Producer"):
            val = pdf_meta.get(key)
            if val and isinstance(val, str):
                doc_info[key.lstrip("/").lower()] = val.strip()

        metadata: dict[str, Any] = {
            "format": "pdf",
            "page_count": num_pages,
            "raw_char_count": len(full_text),
            "doc_info": doc_info,
        }

        return full_text, metadata
