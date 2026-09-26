import hashlib
import re
import urllib.parse
from pathlib import Path

from app.services.document_pipeline.errors import DocumentValidationError

# Supported MIME mappings
ALLOWED_EXTENSIONS_TO_MIME = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}

DEFAULT_MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB


def compute_checksum(content: bytes) -> str:
    """Compute SHA-256 hexadecimal digest for binary file content."""
    return hashlib.sha256(content).hexdigest()


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal, control characters,

    and shell injection attacks.
    """
    if not filename or not filename.strip():
        raise DocumentValidationError("Filename cannot be empty")

    # 1. URL-decode and extract base filename eliminating path traversal (../../ and ..\..\)
    unquoted = urllib.parse.unquote(filename)
    normalized = unquoted.replace("\\", "/")
    name = normalized.split("/")[-1]

    # 2. Remove null bytes and control characters
    name = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", name)

    # 3. Replace unsafe characters, keeping only alphanumeric, hyphens, underscores, dots
    base, sep, ext = name.rpartition(".")
    if not sep:
        base = name
        ext = ""

    # Sanitize base name
    clean_base = re.sub(r"[^a-zA-Z0-9_-]", "_", base)
    clean_base = re.sub(r"_+", "_", clean_base).strip("._-")

    # Sanitize extension
    clean_ext = re.sub(r"[^a-zA-Z0-9]", "", ext).lower()

    if not clean_base:
        clean_base = "document"

    sanitized = f"{clean_base}.{clean_ext}" if clean_ext else clean_base

    # Limit filename length
    if len(sanitized) > 200:
        if clean_ext:
            sanitized = f"{clean_base[: 195 - len(clean_ext)]}.{clean_ext}"
        else:
            sanitized = clean_base[:200]

    return sanitized


def validate_file_size(size: int, max_bytes: int = DEFAULT_MAX_FILE_SIZE) -> None:
    """Validate that file size is non-zero and within configured maximum boundary."""
    if size <= 0:
        raise DocumentValidationError("File is empty (0 bytes). Upload a non-empty document.")
    if size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        raise DocumentValidationError(
            f"File size ({size / (1024 * 1024):.2f} MB) exceeds maximum allowed size ({max_mb:.1f} MB)"
        )


def detect_and_validate_mime(content: bytes, filename: str) -> str:
    """Validate file type by checking extension and content magic bytes."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS_TO_MIME:
        allowed_list = ", ".join(ALLOWED_EXTENSIONS_TO_MIME.keys())
        raise DocumentValidationError(
            f"Unsupported file type '{ext}'. Allowed extensions are: {allowed_list}"
        )

    expected_mime = ALLOWED_EXTENSIONS_TO_MIME[ext]

    # Content-level inspection & magic byte verification
    if ext == ".pdf":
        # PDFs must start with %PDF- header within the first 1024 bytes
        header = content[:1024]
        if b"%PDF-" not in header:
            raise DocumentValidationError("Invalid PDF document: Missing '%PDF-' header signature")
    elif ext in {".txt", ".md", ".markdown"}:
        # Verify text is decodable as text (prevent binaries renamed to .txt)
        # Check first 8KB for null bytes which indicate binary executable/data
        sample = content[:8192]
        if b"\x00" in sample:
            raise DocumentValidationError(
                f"Binary content detected in text file '{filename}'. Only plain text/markdown is permitted."
            )
        try:
            # Check UTF-8 decoding
            sample.decode("utf-8")
        except UnicodeDecodeError:
            try:
                # Fallback check for Latin-1
                sample.decode("latin-1")
            except Exception as e:
                raise DocumentValidationError(
                    f"Unable to decode text file '{filename}': {e!s}"
                ) from e

    return expected_mime
