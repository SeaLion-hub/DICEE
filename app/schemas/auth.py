"""Auth·JWT 관련 Pydantic 스키마. extra='forbid'로 페이로드 오염 방지."""

from pydantic import BaseModel, ConfigDict, Field


class GoogleTokenResponse(BaseModel):
    """구글 OAuth 토큰 교환 응답. model_validate로 검증 (cast 금지)."""

    id_token: str
    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None = None
    scope: str | None = None
    refresh_token: str | None = None


class TokenPayload(BaseModel):
    """OAuth code 교환 요청. code/redirect_uri 길이·형식 제약. 알 수 없는 필드 거부."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="구글 OAuth Authorization Code",
    )
    redirect_uri: str | None = Field(
        None,
        max_length=2048,
        description="OAuth redirect_uri (허용 목록과 일치해야 함)",
    )


class TokenResponse(BaseModel):
    """JWT 토큰 응답 (응답 body JSON 방식)."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token 만료 시간(초)")


class RefreshTokenPayload(BaseModel):
    """Refresh token으로 재발급 요청. extra='forbid'."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(..., min_length=1)
