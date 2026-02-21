"""Auth Service. 구글 OAuth code 검증, User upsert, JWT 발급."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from pydantic import ValidationError
from pyjwt_key_fetcher import AsyncKeyFetcher
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import transaction
from app.core.redis import add_access_to_blocklist, is_access_blocked
from app.repositories.user_repository import increment_refresh_token_version, upsert_by_provider_uid
from app.schemas.auth import GoogleTokenResponse, TokenResponse
from app.schemas.user import UserBase

logger = logging.getLogger(__name__)


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
    Pydantic 스키마로 검증. 네트워크 예외(Timeout, Connect) 시 AuthError로 변환(500 전파 방지).
    """
    client_secret = settings.google_client_secret.get_secret_value()
    try:
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
    except (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
    ) as e:
        logger.warning("Google token exchange network error: %s", e, exc_info=True)
        raise AuthError("Google auth temporarily unavailable") from e
    if resp.status_code != 200:
        logger.warning("Google token exchange failed: %s %s", resp.status_code, resp.text)
        raise AuthError("Invalid or expired authorization code")

    data = resp.json()
    try:
        return GoogleTokenResponse.model_validate(data)
    except ValidationError as e:
        raise AuthError("Invalid Google token response") from e


async def decode_google_id_token(
    id_token_str: str, key_fetcher: AsyncKeyFetcher
) -> dict[str, Any]:
    """구글 ID token 서명 검증 후 디코딩. key_fetcher는 lifespan 싱글톤(Depends)."""
    try:
        key_entry = await key_fetcher.get_key(id_token_str)
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
    Access + Refresh JWT 생성. Access에는 jti 포함(Blocklist 무효화용).
    token_version: 로그아웃/탈취 시 서버에서 무효화하기 위해 User.refresh_token_version과 연동.
    """
    secret = settings.jwt_secret.get_secret_value()
    if not secret:
        raise AuthError("JWT_SECRET not configured")
    now = datetime.now(UTC)
    access_payload = {
        "sub": str(user_id),
        "type": "access",
        "jti": str(uuid.uuid4()),
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


async def verify_access_token(
    encoded: str,
    redis_blocklist_client: Any = None,
    *,
    fail_closed: bool = True,
) -> dict[str, Any]:
    """
    Access JWT 검증. iss/aud/type=access 확인 후 Blocklist 조회.
    Redis 장애 시: fail_closed=True면 인증 거부, False면 서명만 믿고 통과.
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
        jti = payload.get("jti")
        if redis_blocklist_client is not None and jti:
            blocked = await is_access_blocked(
                redis_blocklist_client, jti, fail_closed=fail_closed
            )
            if blocked:
                raise AuthError("Token revoked or invalid")
        return payload
    except AuthError:
        raise
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid access token: %s", e)
        raise AuthError("Invalid or expired token") from e


async def revoke_refresh_tokens_for_user(
    session: AsyncSession, user_id: int
) -> None:
    """해당 유저의 refresh_token_version 증가 → 기존 Refresh 토큰 전부 무효화."""
    await increment_refresh_token_version(session, user_id)


def _allowed_redirect_uris() -> set[str]:
    """설정된 허용 redirect_uri 목록(쉼표 구분). 비어 있으면 빈 set(검사 생략)."""
    raw = (settings.google_redirect_uris or "").strip()
    if not raw:
        return set()
    return {u.strip() for u in raw.split(",") if u.strip()}


async def google_login(
    code: str,
    redirect_uri: str | None = None,
    *,
    http_client: httpx.AsyncClient,
    key_fetcher: AsyncKeyFetcher,
) -> TokenResponse:
    """
    구글 OAuth code로 로그인. redirect_uri allowlist·sub 클레임 필수 검증(Fail-fast).
    1. redirect_uri 허용 목록 검사(설정 시)
    2. code → 구글 토큰 교환
    3. id_token JWKS 검증 후 프로필 추출, sub 필수(누락 시 AuthError)
    4. User upsert, JWT 발급
    """
    allowed = _allowed_redirect_uris()
    if allowed and redirect_uri is not None and redirect_uri.strip() not in allowed:
        raise AuthError("redirect_uri not allowed")
    token_data = await exchange_google_code(code, redirect_uri, http_client)
    id_token = token_data.id_token

    claims = await decode_google_id_token(id_token, key_fetcher)
    provider_user_id = claims.get("sub")
    if not provider_user_id or not str(provider_user_id).strip():
        raise AuthError("Invalid id_token: missing sub")
    provider_user_id = str(provider_user_id).strip()
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


async def logout_user(
    user_id: int,
    *,
    access_jti: str | None = None,
    ttl_seconds: int | None = None,
    redis_blocklist_client: Any = None,
) -> None:
    """
    해당 유저의 refresh_token_version 증가 → 기존 Refresh 토큰 전부 무효화.
    access_jti·ttl_seconds·redis_blocklist_client가 있으면 해당 Access Token을 Blocklist에 등록.
    """
    async with transaction() as session:
        await revoke_refresh_tokens_for_user(session, user_id)
    if redis_blocklist_client and access_jti and ttl_seconds and ttl_seconds > 0:
        await add_access_to_blocklist(
            redis_blocklist_client, access_jti, ttl_seconds
        )
