from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Payload for user authentication."""

    email: EmailStr = Field(..., description="Registered email address")
    password: str = Field(..., min_length=1, description="Account password")


class TokenResponse(BaseModel):
    """Token response returned upon successful login or refresh."""

    access_token: str = Field(..., description="JWT bearer access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token authentication scheme")
    expires_in: int = Field(..., description="Access token expiration window in seconds")


class RefreshTokenRequest(BaseModel):
    """Payload for issuing a new access token via refresh token."""

    refresh_token: str = Field(..., description="Valid signed JWT refresh token")


class LogoutRequest(BaseModel):
    """Optional payload for logout specifying a refresh token to invalidate."""

    refresh_token: str | None = Field(default=None, description="Optional refresh token to revoke")


class LogoutResponse(BaseModel):
    """Acknowledgement of successful logout and token revocation."""

    message: str = Field(default="Successfully logged out", description="Status message")
