from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application runtime settings loaded from environment variables."""

    # Application Metadata
    APP_NAME: str = "LifeThread Backend"
    PROJECT_NAME: str = "LifeThread API"
    PROJECT_DESCRIPTION: str = (
        "Production-grade backend foundation for LifeThread persistent AI goal execution platform."
    )
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # API Routing
    API_V1_STR: str = "/api/v1"
    DOCS_URL: str = "/docs"
    REDOC_URL: str = "/redoc"
    OPENAPI_URL: str = "/openapi.json"

    # Server Network
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Database (PostgreSQL Connection Parameters)
    POSTGRES_USER: str = "lifethread_user"
    POSTGRES_PASSWORD: str = "lifethread_password_dev_only"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "lifethread_db"
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://lifethread_user:lifethread_password_dev_only@localhost:5432/lifethread_db",
        description="SQLAlchemy async connection string for PostgreSQL",
    )

    # Database Connection Pool Settings
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True
    DB_ECHO: bool = False

    # Cache (Redis)
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # Authentication & Security
    JWT_SECRET_KEY: str = Field(
        default="dev_secret_key_change_in_production_min_32_bytes_long!",
        description="Cryptographic secret key for signing JWT tokens",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # LLM Provider Configuration (Interface abstraction placeholders)
    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str = "CHANGEME_IN_PRODUCTION"
    ANTHROPIC_API_KEY: str = "CHANGEME_IN_PRODUCTION"

    # Security Hardening (Module 25)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 120
    RATE_LIMIT_BURST_CAPACITY: int = 30
    SECURITY_HEADERS_ENABLED: bool = True
    AUDIT_LOG_ENABLED: bool = True
    STRICT_SECRET_VALIDATION: bool = False  # Set to True in production to reject dev default secrets
    MCP_INTERNAL_TOKEN: str = Field(
        default="mcp_internal_dev_secret_token_change_in_production",
        description="Shared secret for internal MCP to backend authentication",
    )

    # AWS AI Integration Configuration (Module 35)
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_SESSION_TOKEN: str | None = None
    AWS_ROLE_ARN: str | None = None
    AWS_BEDROCK_DEFAULT_MODEL: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    AWS_BEDROCK_FAST_MODEL: str = "anthropic.claude-3-haiku-20240307-v1:0"
    AWS_BEDROCK_EMBEDDING_MODEL: str = "amazon.titan-embed-text-v2:0"
    AWS_BEDROCK_TIMEOUT_SECONDS: float = 30.0
    AWS_BEDROCK_MAX_RETRIES: int = 3
    AWS_BEDROCK_COST_TRACKING_ENABLED: bool = True
    AWS_BEDROCK_FALLBACK_ON_ERROR: bool = True
    AWS_AGENTCORE_AGENT_ID: str | None = None
    AWS_AGENTCORE_AGENT_ALIAS_ID: str | None = None
    AWS_STRANDS_KNOWLEDGE_BASE_ID: str | None = None

    # Demo & Development Dataset Configuration (Module 46)
    ALLOW_DEMO_DATA: bool = Field(
        default=True,
        description="Whether demo scenario loader endpoints and CLI scripts are allowed to execute (disabled in production)",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()
