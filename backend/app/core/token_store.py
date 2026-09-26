import logging
import time
from datetime import datetime
from typing import ClassVar

logger = logging.getLogger("lifethread.auth.tokens")


class TokenDenylist:
    """Thread-safe token revocation registry.

    Tracks revoked token IDs (jti) to prevent reuse after logout or token rotation.
    Provides fast in-memory tracking with automatic expiry pruning and Redis integration readiness.
    """

    _revoked_tokens: ClassVar[dict[str, float]] = {}

    @classmethod
    def revoke(cls, jti: str, expire_at: float | datetime | None = None) -> None:
        """Revoke a token identifier until its expiration timestamp."""
        cls._prune_expired()
        if expire_at is None:
            exp_timestamp = time.time() + 3600.0
        elif isinstance(expire_at, datetime):
            exp_timestamp = expire_at.timestamp()
        else:
            val = float(expire_at)
            # If val is a relative duration (e.g. 1800s) rather than an absolute epoch timestamp
            if val < 1_000_000_000:
                exp_timestamp = time.time() + val
            else:
                exp_timestamp = val
        cls._revoked_tokens[jti] = exp_timestamp
        logger.info("Revoked token identifier", extra={"jti": jti[:8]})

    @classmethod
    def is_revoked(cls, jti: str) -> bool:
        """Check if a token identifier has been revoked."""
        cls._prune_expired()
        return jti in cls._revoked_tokens

    @classmethod
    def is_denylisted(cls, jti: str) -> bool:
        """Check if a token identifier has been denylisted (alias for is_revoked)."""
        return cls.is_revoked(jti)

    @classmethod
    def denylist_token(cls, jti: str, expire_at: float | datetime | None = None) -> None:
        """Denylist a token identifier (alias for revoke)."""
        cls.revoke(jti, expire_at)

    @classmethod
    def _prune_expired(cls) -> None:
        """Prune tokens whose natural expiration has elapsed."""
        now = time.time()
        expired_keys = [k for k, exp in cls._revoked_tokens.items() if exp <= now]
        for k in expired_keys:
            cls._revoked_tokens.pop(k, None)

    @classmethod
    def clear(cls) -> None:
        """Clear all revoked tokens (useful in test suites)."""
        cls._revoked_tokens.clear()
