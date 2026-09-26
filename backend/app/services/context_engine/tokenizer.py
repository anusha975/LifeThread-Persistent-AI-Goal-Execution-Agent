import math
import re
from functools import lru_cache

try:
    import tiktoken

    _ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODER = None


@lru_cache(maxsize=4096)
def count_tokens(text: str) -> int:
    """Accurately count tokens using cl100k_base with a character-based fallback."""
    if not text:
        return 0

    if _ENCODER is not None:
        try:
            return len(_ENCODER.encode(text, disallowed_special=()))
        except Exception:
            pass

    # Fallback heuristic: ~4 characters per token for English text
    words = len(re.findall(r"\w+", text))
    char_estimate = math.ceil(len(text) / 4.0)
    word_estimate = math.ceil(words * 1.3)
    return max(1, max(char_estimate, word_estimate))


def truncate_to_token_limit(text: str, max_tokens: int) -> str:
    """Truncate text to stay within the max_tokens limit cleanly."""
    if max_tokens <= 0:
        return ""

    if count_tokens(text) <= max_tokens:
        return text

    if _ENCODER is not None:
        try:
            tokens = _ENCODER.encode(text, disallowed_special=())
            if len(tokens) > max_tokens:
                truncated_tokens = tokens[:max_tokens]
                return _ENCODER.decode(truncated_tokens) + "..."
        except Exception:
            pass

    # Character-based approximation fallback
    approx_chars = max(1, max_tokens * 4)
    if len(text) > approx_chars:
        # Split on word boundary
        truncated = text[:approx_chars].rsplit(" ", 1)[0]
        return truncated + "..."
    return text
