from fastapi import Request

from app.core.config import Settings, get_settings


def get_app_settings() -> Settings:
    """Dependency provider for cached application settings."""
    return get_settings()


def get_request_id(request: Request) -> str:
    """Dependency provider extracting current request ID from request state."""
    return getattr(request.state, "request_id", "unknown")
