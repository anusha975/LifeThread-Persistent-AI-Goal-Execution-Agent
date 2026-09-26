from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    """Configuration settings for standalone MCP server."""

    MCP_SERVER_HOST: str = "0.0.0.0"
    MCP_SERVER_PORT: int = 8001
    MCP_SERVER_NAME: str = "LifeThread MCP Server"
    MCP_TRANSPORT: str = "streamable_http"  # streamable_http, http, or stdio
    MCP_API_KEY: str = "lifethread-mcp-secret-key"
    MCP_AUTH_ENABLED: bool = True
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_mcp_settings() -> MCPSettings:
    return MCPSettings()
