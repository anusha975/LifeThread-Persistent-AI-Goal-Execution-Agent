from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Structured health check response."""

    status: str = Field(default="ok", description="Operational health status")
    service: str = Field(default="lifethread-api", description="Service identifier")
    version: str = Field(default="0.1.0", description="Application version")


class ReadinessResponse(BaseModel):
    """Structured readiness check response."""

    status: str = Field(default="ready", description="Service readiness status")
    service: str = Field(default="lifethread-api", description="Service identifier")
    version: str = Field(default="0.1.0", description="Application version")
    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Readiness status of internal dependencies",
    )
