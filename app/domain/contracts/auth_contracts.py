"""Auth 도메인 계약. 서비스 반환 타입만 정의. 직렬화는 라우터에서 스키마로."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoogleTokenResult:
    """구글 OAuth 토큰 교환 결과. exchange_google_code 반환용."""

    id_token: str
    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None = None
    scope: str | None = None
    refresh_token: str | None = None


@dataclass(frozen=True)
class TokenResult:
    """JWT 토큰 쌍 결과. google_login / refresh_tokens 반환용."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 0
