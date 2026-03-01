"""Auth Service. 구글 OAuth code 검증, User upsert, JWT 발급."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, cast
from urllib.parse import unquote, urlparse

import httpx
import jwt
from pyjwt_key_fetcher import AsyncKeyFetcher
from redis.asyncio import Redis as RedisAsyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config.jwt import resolve_jwt_signing_algorithm
from app.core.ip_hmac import compute_ip_hmac
from app.core.metrics import REFRESH_TOKEN_REUSE_ATTEMPT_TOTAL, increment
from app.core.redis import BlocklistUnavailableError, is_access_blocked
from app.core.user_id_hmac import compute_user_id_hash
from app.domain.contracts.auth_contracts import GoogleTokenResult, TokenResult
from app.domain.contracts.user_contracts import UserUpsertCmd
from app.repositories.login_audit_repository import create_login_audit
from app.repositories.user_repository import (
    increment_refresh_token_version,
    rotate_refresh_token_version,
    upsert_by_provider_uid,
)

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """사용자 인증/권한 예외. Router에서 400 또는 401로 변환."""

    pass


class AuthServiceUnavailableError(Exception):
    """외부 인증 장애(구글 등) 시 사용. Router에서 503 Service Unavailable로 변환."""

    pass


async def exchange_google_code(
    code: str,
    redirect_uri: str | None,
    client: httpx.AsyncClient,
    code_verifier: str | None = None,
) -> GoogleTokenResult:
    """
    구글 OAuth Authorization Code를 액세스 토큰으로 교환.
    code_verifier가 있으면 PKCE로 전달. 네트워크 실패 시 AuthServiceUnavailableError(503).
    """
    client_secret = settings.google_client_secret.get_secret_value()
    data: dict[str, str] = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri or "http://localhost",
        "grant_type": "authorization_code",
    }
    if code_verifier:
        data["code_verifier"] = code_verifier
    try:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
    ) as e:
        logger.warning("Google token exchange network error: %s", e, exc_info=True)
        raise AuthServiceUnavailableError("Google auth temporarily unavailable") from e
    if resp.status_code != 200:
        error_code = ""
        try:
            data = resp.json()
            if isinstance(data, dict):
                error_code = data.get("error", "") or ""
                desc = data.get("error_description", "")
                if desc:
                    error_code = f"{error_code}:{desc[:80]}" if error_code else desc[:80]
        except Exception:
            pass
        logger.warning(
            "Google token exchange failed: status=%s error=%s",
            resp.status_code,
            error_code or "(no error code)",
        )
        raise AuthError("Invalid or expired authorization code")

    try:
        data = resp.json()
    except ValueError as e:
        raise AuthError("Invalid Google token response") from e
    if not isinstance(data, dict) or not data.get("id_token"):
        raise AuthError("Invalid Google token response")
    expires_in_raw = data.get("expires_in")
    try:
        expires_in = int(expires_in_raw) if expires_in_raw is not None else None
    except (TypeError, ValueError) as e:
        raise AuthError("Invalid Google token response") from e
    return GoogleTokenResult(
        id_token=str(data["id_token"]),
        access_token=str(data.get("access_token", "")),
        token_type=str(data.get("token_type", "Bearer")),
        expires_in=expires_in,
        scope=str(data["scope"]) if data.get("scope") is not None else None,
        refresh_token=str(data["refresh_token"]) if data.get("refresh_token") is not None else None,
    )


async def decode_google_id_token(id_token_str: str, key_fetcher: AsyncKeyFetcher) -> dict[str, Any]:
    """구글 ID token 서명 검증(키는 key_fetcher·lifespan 공유·Depends)."""
    try:
        key_entry = await key_fetcher.get_key(id_token_str)
        payload = jwt.decode(
            jwt=id_token_str,
            audience=settings.google_client_id,
            options={"verify_exp": True, "verify_aud": True},
            **key_entry,
        )
        return cast(dict[str, Any], payload)
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid id_token: %s", e)
        raise AuthError("Invalid id_token") from e
    except Exception as e:
        logger.warning("ID token verification failed (JWKS/network): %s", e, exc_info=True)
        raise AuthServiceUnavailableError("ID token verification temporarily unavailable") from e


def _jwt_encode_key_and_algorithm() -> tuple[str | bytes, str]:
    """Resolve encode algorithm/key using JWT_SIGNING_MODE."""
    private_key = settings.jwt_private_key_pem.get_secret_value() if settings.jwt_private_key_pem else None
    public_key = settings.jwt_public_key_pem.get_secret_value() if settings.jwt_public_key_pem else None
    secret = settings.jwt_secret.get_secret_value()
    try:
        algorithm = resolve_jwt_signing_algorithm(
            settings.jwt_signing_mode,
            jwt_secret=secret,
            jwt_private_key_pem=private_key,
            jwt_public_key_pem=public_key,
        )
    except ValueError as e:
        raise AuthError(str(e)) from e

    if algorithm == "RS256":
        assert private_key is not None
        return private_key.strip(), "RS256"
    return secret, "HS256"


def _jwt_decode_key_and_algorithm() -> tuple[str | bytes, str]:
    """Resolve decode algorithm/key using JWT_SIGNING_MODE."""
    private_key = settings.jwt_private_key_pem.get_secret_value() if settings.jwt_private_key_pem else None
    public_key = settings.jwt_public_key_pem.get_secret_value() if settings.jwt_public_key_pem else None
    secret = settings.jwt_secret.get_secret_value()
    try:
        algorithm = resolve_jwt_signing_algorithm(
            settings.jwt_signing_mode,
            jwt_secret=secret,
            jwt_private_key_pem=private_key,
            jwt_public_key_pem=public_key,
        )
    except ValueError as e:
        raise AuthError(str(e)) from e

    if algorithm == "RS256":
        assert public_key is not None
        return public_key.strip(), "RS256"
    return secret, "HS256"


def create_jwt_pair(user_id: uuid.UUID, token_version: int = 0) -> tuple[str, str]:
    """
    Access + Refresh JWT 생성. Access에는 jti 포함(Blocklist 무효화 사용).
    token_version: 로그아웃/탈퇴 등 서비스에서 무효화하기 위해 User.refresh_token_version과 동기.
    RS256 키 있으면 RS256, 없으면 HS256 사용.
    """
    key, algorithm = _jwt_encode_key_and_algorithm()
    now = datetime.now(UTC)
    access_payload = {
        "sub": str(user_id),
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": now + timedelta(seconds=settings.jwt_access_expire_seconds),
        "iat": now,
        "nbf": now,
    }
    refresh_payload = {
        "sub": str(user_id),
        "type": "refresh",
        "token_version": token_version,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": now + timedelta(days=settings.jwt_refresh_expire_days),
        "iat": now,
        "nbf": now,
    }
    access_token = jwt.encode(access_payload, key, algorithm=algorithm)
    refresh_token = jwt.encode(refresh_payload, key, algorithm=algorithm)
    return access_token, refresh_token


async def verify_access_token(
    encoded: str,
    redis_blocklist_client: RedisAsyncio | None = None,
    *,
    fail_closed: bool = True,
) -> dict[str, Any]:
    """
    Access JWT 검증. iss/aud/type=access 확인 후 Blocklist 조회.
    Redis 설정 시 fail_closed=True면 인증 거부, False면 서명만 검증 후 통과.
    RS256 키 있으면 RS256, 없으면 HS256으로 검증.
    """
    key, algorithm = _jwt_decode_key_and_algorithm()
    try:
        payload = jwt.decode(
            encoded,
            key,
            algorithms=[algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "sub", "type", "jti", "nbf"]},
        )
        if payload.get("type") != "access":
            raise AuthError("Invalid token type")
        jti = payload.get("jti")
        if fail_closed and redis_blocklist_client is None:
            raise BlocklistUnavailableError("Blocklist required but Redis not configured")
        if redis_blocklist_client is not None and jti:
            blocked = await is_access_blocked(redis_blocklist_client, jti, fail_closed=fail_closed)
            if blocked:
                raise AuthError("Token revoked or invalid")
        return cast(dict[str, Any], payload)
    except AuthError:
        raise
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid access token: %s", e)
        raise AuthError("Invalid or expired token") from e


def verify_refresh_token(encoded: str) -> dict[str, Any]:
    """
    Refresh JWT 검증. type=refresh, token_version, sub, exp 필수.
    만료·폐지 시 AuthError. 반환 payload에는 sub, token_version 포함.
    """
    key, algorithm = _jwt_decode_key_and_algorithm()
    try:
        payload = jwt.decode(
            encoded,
            key,
            algorithms=[algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "sub", "type", "token_version", "nbf"]},
        )
        if payload.get("type") != "refresh":
            raise AuthError("Invalid token type")
        return cast(dict[str, Any], payload)
    except AuthError:
        raise
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid refresh token: %s", e)
        raise AuthError("Invalid or expired refresh token") from e


async def refresh_tokens(
    refresh_token: str,
    session: AsyncSession,
) -> TokenResult:
    """
    Refresh 토큰으로 Access/Refresh 쌍 발급. 1회성: 이전 CAS 방식처럼 version으로 발급.
    동일 사용 중인 토큰은 만료·폐지 시 AuthError(무효화된 토큰).
    """
    payload = verify_refresh_token(refresh_token)
    user_id = uuid.UUID(payload["sub"])
    raw_version = payload.get("token_version")
    if raw_version is None:
        raise AuthError("Refresh token revoked or invalid")
    try:
        token_version = int(raw_version)
    except (TypeError, ValueError):
        raise AuthError("Refresh token revoked or invalid")
    if token_version < 0:
        raise AuthError("Refresh token revoked or invalid")
    new_version = await rotate_refresh_token_version(session, user_id, token_version)
    if new_version is None:
        user_id_hash = compute_user_id_hash(user_id)
        logger.warning(
            "Refresh token reuse attempt (CAS failed)",
            extra={"event": "refresh_token_reuse", "user_id_hash": user_id_hash},
        )
        increment(REFRESH_TOKEN_REUSE_ATTEMPT_TOTAL)
        raise AuthError("Refresh token revoked or invalid")
    access_token, new_refresh_token = create_jwt_pair(user_id, token_version=new_version)
    return TokenResult(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_expire_seconds,
    )


async def revoke_refresh_tokens_for_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """해당 사용자의 refresh_token_version 증가 시 원본 Refresh 토큰 무효화."""
    await increment_refresh_token_version(session, user_id)


def _normalize_redirect_uri(uri: str) -> str:
    """
    redirect_uri 정규화: scheme·host 유지, path만 unquote, query·fragment·userinfo 거부.
    보안 상 유의: unquote 1회만(path에 '%'가 남으면 거부).
    """
    s = (uri or "").strip()
    if not s:
        raise AuthError("redirect_uri required")
    parsed = urlparse(s)
    if (parsed.scheme or "").lower() not in ("http", "https"):
        raise AuthError("redirect_uri must be http or https")
    if parsed.username or parsed.password or not parsed.hostname:
        raise AuthError("redirect_uri host is invalid")
    if parsed.query or parsed.fragment:
        raise AuthError("redirect_uri must not contain query or fragment")
    host = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port else ""
    path = unquote(parsed.path or "/").rstrip("/") or "/"
    if "%" in path:
        raise AuthError("redirect_uri invalid encoding")
    return f"{parsed.scheme.lower()}://{host}{port}{path}"


@lru_cache(maxsize=1)
def _allowed_redirect_uris() -> set[str]:
    """
    설정·허용 redirect_uri 목록(쉼표 구분). 정규화 후 set 반환. 비어 있으면 빈 set.
    P0 fail-closed: 설정값이 있는데 유효한 URI가 하나도 없으면 AuthError. 허용 목록이 비면 검증 생략해도 됨.
    """
    raw = (settings.google_redirect_uris or "").strip()
    if not raw:
        return set()
    result: set[str] = set()
    for u in raw.split(","):
        u = u.strip()
        if not u:
            continue
        try:
            result.add(_normalize_redirect_uri(u))
        except AuthError:
            continue
    if not result:
        raise AuthError(
            "google_redirect_uris: no valid redirect URIs (all entries invalid or malformed). Fix configuration."
        )
    return result


async def google_login(
    session: AsyncSession,
    code: str,
    redirect_uri: str | None = None,
    *,
    http_client: httpx.AsyncClient,
    key_fetcher: AsyncKeyFetcher,
    client_ip: str | None = None,
    code_verifier: str | None = None,
) -> TokenResult:
    """
    구글 OAuth code로 로그인, redirect_uri allowlist·sub 보존 검증(Fail-fast).
    1. redirect_uri 허용 목록 검증·설정
    2. code로 구글 토큰 교환
    3. id_token JWKS 검증·키로 디코딩, sub 필수(없으면 AuthError)
    4. User upsert, JWT 발급
    문서·배포 검증·운영 시 참고만 할 것. session은 Depends(get_db)로 주입받아 사용.
    """
    allowed = _allowed_redirect_uris()
    if allowed:
        try:
            normalized = _normalize_redirect_uri(redirect_uri or "")
        except AuthError:
            raise
        if normalized not in allowed:
            raise AuthError("redirect_uri not allowed")
    else:
        # 설정 생략 시에만 검증 생략. (google_redirect_uris 비어 있음. 키로 범위로부터 설정 무효.)
        normalized = redirect_uri or "http://localhost"
    token_result = await exchange_google_code(code, normalized, http_client, code_verifier=code_verifier)
    id_token = token_result.id_token

    claims = await decode_google_id_token(id_token, key_fetcher)
    provider_user_id = claims.get("sub")
    if not provider_user_id or not str(provider_user_id).strip():
        raise AuthError("Invalid id_token: missing sub")
    provider_user_id = str(provider_user_id).strip()
    email = claims.get("email")
    name = claims.get("name")

    cmd = UserUpsertCmd(
        provider="google",
        provider_user_id=provider_user_id,
        email=email,
        name=name,
        profile_json=None,
    )
    user = await upsert_by_provider_uid(session, cmd)

    if client_ip:
        try:
            ip_hmac_val, ip_hmac_key_version = compute_ip_hmac(client_ip)
            await create_login_audit(
                session,
                ip_hmac=ip_hmac_val,
                ip_hmac_key_version=ip_hmac_key_version,
                user_id=user.id,
                provider="google",
            )
        except Exception as e:
            user_id_hash = compute_user_id_hash(user.id)
            logger.warning(
                "Login audit failed: %s",
                e,
                exc_info=True,
                extra={"user_id_hash": user_id_hash},
            )

    version = getattr(user, "refresh_token_version", 0)
    access_token, refresh_token = create_jwt_pair(user.id, token_version=version)
    return TokenResult(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_expire_seconds,
    )


async def logout_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """
    로그아웃 시 DB 선행 수행: Refresh 무효화(refresh_token_version 증가).
    원자성 보장: session.commit() 후 Redis Blocklist를 등록해야 함.
    순서: logout_user 내 commit 후 blocklist. 그래서 Redis 실패 시에도 DB는 이미 반영되어 있음. Blocklist만 미등록됨.
    """
    await revoke_refresh_tokens_for_user(session, user_id)
