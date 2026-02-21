"""Auth Service. 구글 OAuth code 검증, User upsert, JWT 발급."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from pydantic import ValidationError
from pyjwt_key_fetcher import AsyncKeyFetcher
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import transaction
from app.repositories.user_repository import increment_refresh_token_version, upsert_by_provider_uid
from app.schemas.auth import GoogleTokenResponse, TokenResponse
from app.schemas.user import UserBase

logger = logging.getLogger(__name__)

# 구글 ID 토큰 검증용 비동기 JWKS 클라이언트. 이벤트 루프 필요로 인해 첫 사용 시 생성.
_google_key_fetcher: AsyncKeyFetcher | None = None


def _get_google_key_fetcher() -> AsyncKeyFetcher:
    global _google_key_fetcher
    if _google_key_fetcher is None:
        _google_key_fetcher = AsyncKeyFetcher(
            valid_issuers=["https://accounts.google.com"],
        )
    return _google_key_fetcher


class AuthError(Exception):
    """Auth 관련 예외. Router에서 HTTPException으로 변환."""

    pass


async def exchange_google_code(
    code: str,
    redirect_uri: str | None,
    client: httpx.AsyncClient,
) -> GoogleTokenResponse:
    """
    구글 OAuth Authorization Code를 액세스 토큰으로 교환.
    Pydantic 스키마로 검증. client는 앱 생명주기 싱글톤(재사용).
    """
    client_secret = settings.google_client_secret.get_secret_value()
    resp = await client.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri or "http://localhost",
            "grant_type": "authorization_code",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code != 200:
        logger.warning("Google token exchange failed: %s %s", resp.status_code, resp.text)
        raise AuthError("Invalid or expired authorization code")

    data = resp.json()
    try:
        return GoogleTokenResponse.model_validate(data)
    except ValidationError as e:
        raise AuthError("Invalid Google token response") from e


async def decode_google_id_token(id_token_str: str) -> dict[str, Any]:
    """구글 ID token 서명 검증 후 디코딩. 비동기 JWKS(pyjwt-key-fetcher) 사용."""
    try:
        key_entry = await _get_google_key_fetcher().get_key(id_token_str)
        payload = jwt.decode(
            jwt=id_token_str,
            audience=settings.google_client_id,
            options={"verify_exp": True, "verify_aud": True},
            **key_entry,
        )
        return payload
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid id_token: %s", e)
        raise AuthError("Invalid id_token") from e


def create_jwt_pair(user_id: int, token_version: int = 0) -> tuple[str, str]:
    """
    Access + Refresh JWT 생성.
    token_version: 로그아웃/탈취 시 서버에서 무효화하기 위해 User.refresh_token_version과 연동.
    """
    secret = settings.jwt_secret.get_secret_value()
    if not secret:
        raise AuthError("JWT_SECRET not configured")
    now = datetime.now(UTC)
    access_payload = {
        "sub": str(user_id),
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": now + timedelta(seconds=settings.jwt_access_expire_seconds),
        "iat": now,
    }
    refresh_payload = {
        "sub": str(user_id),
        "type": "refresh",
        "token_version": token_version,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": now + timedelta(days=settings.jwt_refresh_expire_days),
        "iat": now,
    }
    access_token = jwt.encode(
        access_payload,
        secret,
        algorithm="HS256",
    )
    refresh_token = jwt.encode(
        refresh_payload,
        secret,
        algorithm="HS256",
    )
    return access_token, refresh_token


def verify_access_token(encoded: str) -> dict[str, Any]:
    """
    Access JWT 검증. iss/aud/type=access 확인 후 payload 반환.
    로그아웃·인가 시 사용. 실패 시 AuthError.
    """
    try:
        payload = jwt.decode(
            encoded,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "sub", "type"]},
        )
        if payload.get("type") != "access":
            raise AuthError("Invalid token type")
        return payload
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid access token: %s", e)
        raise AuthError("Invalid or expired token") from e


async def revoke_refresh_tokens_for_user(
    session: AsyncSession, user_id: int
) -> None:
    """해당 유저의 refresh_token_version 증가 → 기존 Refresh 토큰 전부 무효화."""
    await increment_refresh_token_version(session, user_id)


async def google_login(
    code: str,
    redirect_uri: str | None = None,
    *,
    http_client: httpx.AsyncClient,
) -> TokenResponse:
    """
    구글 OAuth code로 로그인. 트랜잭션 경계는 서비스 레이어(transaction())에서만 제어.
    1. code → 구글 토큰 교환
    2. id_token 비동기 JWKS 검증 후 프로필 추출
    3. User upsert
    4. JWT 발급 (refresh_token_version 연동)
    """
    token_data = await exchange_google_code(code, redirect_uri, http_client)
    id_token = token_data.id_token

    claims = await decode_google_id_token(id_token)
    provider_user_id = claims.get("sub") or ""
    email = claims.get("email")
    name = claims.get("name")

    user_base = UserBase(email=email, name=name, profile_json=None)

    async with transaction() as session:
        user = await upsert_by_provider_uid(
            session, "google", provider_user_id, user_base
        )
        await session.flush()
        await session.refresh(user)

        version = getattr(user, "refresh_token_version", 0)
        access_token, refresh_token = create_jwt_pair(user.id, token_version=version)
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.jwt_access_expire_seconds,
        )


async def logout_user(user_id: int) -> None:
    """해당 유저의 refresh_token_version 증가 → 기존 Refresh 토큰 전부 무효화. 트랜잭션은 서비스에서 제어."""
    async with transaction() as session:
        await revoke_refresh_tokens_for_user(session, user_id)
