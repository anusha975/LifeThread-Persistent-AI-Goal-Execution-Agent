import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserBase(BaseModel):
    """Base user attributes."""

    email: EmailStr = Field(..., description="Valid unique email address")
    display_name: str | None = Field(default=None, max_length=100, description="User display name")
    timezone: str = Field(default="UTC", max_length=50, description="Preferred timezone identifier")


class UserCreate(UserBase):
    """Payload for user registration."""

    password: str = Field(..., min_length=8, max_length=128, description="Plaintext password")

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserResponse(UserBase):
    """Public user profile response (password hash strictly omitted)."""

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
