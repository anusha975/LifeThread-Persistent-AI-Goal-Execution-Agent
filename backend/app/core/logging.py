import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Context variable to hold active request ID across async tasks
request_id_ctx: ContextVar[str | None] = ContextVar("request_id_ctx", default=None)


class JSONFormatter(logging.Formatter):
    """Structured JSON formatter for production-ready logs."""

    def format(self, record: logging.LogRecord) -> str:
        req_id = getattr(record, "request_id", None) or request_id_ctx.get()

        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if req_id:
            log_payload["request_id"] = req_id

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        # Include custom extra attributes if passed
        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "request_id",
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in standard_attrs}
        if extras:
            log_payload["extra"] = extras

        return json.dumps(log_payload)


class ConsoleFormatter(logging.Formatter):
    """Clean console formatter with request ID context."""

    def format(self, record: logging.LogRecord) -> str:
        req_id = getattr(record, "request_id", None) or request_id_ctx.get()
        req_prefix = f" [{req_id[:8]}]" if req_id else ""
        asctime = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        message = record.getMessage()
        res = f"{asctime} [{record.levelname}]{req_prefix} {record.name}: {message}"
        if record.exc_info:
            res += "\n" + self.formatException(record.exc_info)
        return res


def setup_logging(level: str = "INFO", json_format: bool = False) -> None:
    """Configure root logger with structured formatting."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())

    root_logger.addHandler(handler)
