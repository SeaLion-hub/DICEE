"""Auth·JWT 관련 Pydantic 스키마."""

from pydantic import BaseModel, Field


class TokenPayload(BaseModel):
    """OAuth code 교환 요청."""

    code: str = Field(..., description="구글 OAuth Authorization Code")
    redirect_uri: str | None = Field(None, description="OAuth redirect_uri (검증용)")


class TokenResponse(BaseModel):
    """JWT 토큰 응답 (응답 body JSON 방식)."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token 만료 시간(초)")


class RefreshTokenPayload(BaseModel):
    """Refresh token으로 재발급 요청."""

    refresh_token: str
