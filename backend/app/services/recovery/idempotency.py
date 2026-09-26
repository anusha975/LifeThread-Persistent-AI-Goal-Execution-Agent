import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("lifethread.services.recovery.idempotency")


class IdempotencyRecord:
    """Record of an idempotent execution attempt and its cached result."""

    def __init__(self, key: str, expires_at: datetime) -> None:
        self.key = key
        self.status = "IN_PROGRESS"  # IN_PROGRESS, COMPLETED, FAILED
        self.result: Any | None = None
        self.error: str | None = None
        self.created_at = datetime.now(UTC)
        self.completed_at: datetime | None = None
        self.expires_at = expires_at
        self.execution_count = 1

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at


class IdempotencyManager:
    """In-memory thread-safe idempotency manager to prevent duplicate actions or double execution."""

    def __init__(self, default_ttl_seconds: int = 3600) -> None:
        self._default_ttl = default_ttl_seconds
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def start_operation(
        self,
        key: str,
        ttl_seconds: int | None = None,
    ) -> tuple[bool, Any | None]:
        """Attempt to register an operation.

        Returns:
            (can_proceed, cached_result)
            - If operation already completed: (False, cached_result)
            - If operation in-progress: (False, None)
            - If operation is new: (True, None)
        """
        ttl = ttl_seconds or self._default_ttl
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl)

        with self._lock:
            # Clean expired records opportunistically
            self._purge_expired()

            record = self._records.get(key)
            if record is not None and not record.is_expired:
                if record.status == "COMPLETED":
                    record.execution_count += 1
                    logger.info(
                        "Idempotency hit: Operation '%s' already completed. Returning cached result.",
                        key,
                    )
                    return False, record.result
                elif record.status == "IN_PROGRESS":
                    record.execution_count += 1
                    logger.warning(
                        "Idempotency conflict: Operation '%s' is already in-progress.", key
                    )
                    return False, None
                elif record.status == "FAILED":
                    # Failed operations can be retried cleanly
                    record.status = "IN_PROGRESS"
                    record.execution_count += 1
                    record.expires_at = expires_at
                    return True, None

            # New operation
            self._records[key] = IdempotencyRecord(key=key, expires_at=expires_at)
            return True, None

    def complete_operation(self, key: str, result: Any) -> None:
        """Mark operation completed and cache result for future duplicate requests."""
        with self._lock:
            record = self._records.get(key)
            if record is not None:
                record.status = "COMPLETED"
                record.result = result
                record.completed_at = datetime.now(UTC)

    def fail_operation(self, key: str, error: str) -> None:
        """Mark operation failed so subsequent calls can retry cleanly."""
        with self._lock:
            record = self._records.get(key)
            if record is not None:
                record.status = "FAILED"
                record.error = error
                record.completed_at = datetime.now(UTC)

    def release_operation(self, key: str) -> None:
        """Remove record entirely (e.g. after deliberate rollback)."""
        with self._lock:
            self._records.pop(key, None)

    def is_completed(self, key: str) -> bool:
        """Check if an operation key has completed successfully."""
        with self._lock:
            record = self._records.get(key)
            return record is not None and not record.is_expired and record.status == "COMPLETED"

    def get_execution_count(self, key: str) -> int:
        """Get the number of times this operation was called or requested."""
        with self._lock:
            record = self._records.get(key)
            return record.execution_count if record else 0

    def _purge_expired(self) -> None:
        """Remove expired records."""
        expired_keys = [k for k, r in self._records.items() if r.is_expired]
        for k in expired_keys:
            del self._records[k]

    def clear(self) -> None:
        """Reset all idempotency records."""
        with self._lock:
            self._records.clear()


# Global singleton manager
idempotency_manager = IdempotencyManager()
