import re
import unicodedata


def clean_text(raw_text: str) -> str:
    """Clean and normalize extracted document text for chunking and RAG ingestion.

    - Normalizes Unicode to NFKC form.
    - Strips NULL bytes and control characters (preserves newlines and tabs).
    - Normalizes carriage returns (\\r\\n and \\r -> \\n).
    - Strips trailing whitespace per line.
    - Collapses excessive blank lines (max 2 consecutive newlines).
    - Trims outer text.
    """
    if not raw_text:
        return ""

    # 1. Normalize Unicode representation
    text = unicodedata.normalize("NFKC", raw_text)

    # 2. Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. Remove NULL bytes and non-printable control characters (keep \t, \n)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)

    # 4. Strip trailing whitespace from each line
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    # 5. Collapse excessive blank lines (more than 2 consecutive newlines down to 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
