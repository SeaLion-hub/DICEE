"""Auth API. 구글 OAuth + JWT."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_rate_limit import (
    RateLimitUnavailableError,
    check_rate_limit,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_google_key_fetcher, get_httpx_client, get_redis_blocklist
from app.core.network import get_client_ip
from app.core.redis import BlocklistUnavailableError, add_access_to_blocklist
from app.schemas.auth import RefreshTokenPayload, TokenPayload, TokenResponse
from app.services.auth_service import (
    AuthError,
    AuthServiceUnavailableError,
    google_login,
    logout_user,
    refresh_tokens,
    verify_access_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    redis_blocklist=Depends(get_redis_blocklist),
):
    """Authorization Bearer에서 Access JWT 검증 후 user_id(UUID) 반환. Blocklist·Redis 장애 정책 적용."""
    import uuid as uuid_mod
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization")
    try:
        payload = await verify_access_token(
            credentials.credentials,
            redis_blocklist,
            fail_closed=settings.redis_blocklist_fail_closed,
        )
        return uuid_mod.UUID(payload["sub"])
    except (AuthError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


async def get_current_user_id_and_jti(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    redis_blocklist=Depends(get_redis_blocklist),
):
    """Access JWT 검증 후 (user_id UUID, jti) 반환. 로그아웃 시 Blocklist 등록용."""
    import uuid as uuid_mod
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization")
    try:
        payload = await verify_access_token(
            credentials.credentials,
            redis_blocklist,
            fail_closed=settings.redis_blocklist_fail_closed,
        )
        return uuid_mod.UUID(payload["sub"]), payload.get("jti")
    except (AuthError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


@router.post("/google", response_model=TokenResponse)
async def post_google_auth(
    request: Request,
    payload: TokenPayload,
    session: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_httpx_client),
    key_fetcher=Depends(get_google_key_fetcher),
    redis_rate=Depends(get_redis_blocklist),
) -> TokenResponse:
    """
    구글 OAuth Authorization Code로 로그인.
    code를 받아 검증 후 Access/Refresh JWT 반환.
    외부 API 장애(타임아웃 등) → 503, 클라이언트 인증 오류 → 400.
    """
    client_ip = get_client_ip(request)
    if client_ip is None:
        raise HTTPException(
            status_code=503,
            detail="Client IP could not be determined; rate limiting requires a valid client identity.",
        )
    identifier = f"auth_google:{client_ip}"
    try:
        allowed = await check_rate_limit(
            redis_rate,
            identifier=identifier,
            max_requests=getattr(settings, "auth_google_rate_limit_per_minute", 10),
            window_seconds=60,
            require_redis=getattr(settings, "api_rate_limit_require_redis", False),
        )
    except RateLimitUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Rate limiting is temporarily unavailable. Try again later.",
        ) from None
    if not allowed:
        logger.warning(
            "auth google rate limit exceeded",
            extra={"client_ip": client_ip, "identifier": identifier},
        )
        raise HTTPException(
            status_code=429,
            detail="Too many authentication attempts, please try again later.",
        )
    try:
        result = await google_login(
            session,
            payload.code,
            redirect_uri=payload.redirect_uri,
            http_client=http_client,
            key_fetcher=key_fetcher,
            client_ip=client_ip,
        )
        await session.commit()
        return result
    except AuthServiceUnavailableError as e:
        logger.warning("Google auth unavailable: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Authentication service temporarily unavailable",
        ) from e
    except AuthError as e:
        logger.warning("Google login auth error: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Invalid request",
        ) from e


@router.post("/refresh", response_model=TokenResponse)
async def post_refresh(
    request: Request,
    payload: RefreshTokenPayload,
    session: AsyncSession = Depends(get_db),
    redis_rate=Depends(get_redis_blocklist),
) -> TokenResponse:
    """
    Refresh 토큰으로 새 Access/Refresh JWT 발급.
    type=refresh, token_version 검증 후 새 쌍 반환. 무효화된 토큰 시 401.
    """
    client_ip = get_client_ip(request)
    if client_ip is None:
        raise HTTPException(
            status_code=503,
            detail="Client IP could not be determined; rate limiting requires a valid client identity.",
        )
    identifier = f"auth_refresh:{client_ip}"
    try:
        allowed = await check_rate_limit(
            redis_rate,
            identifier=identifier,
            max_requests=getattr(settings, "auth_refresh_rate_limit_per_minute", 60),
            window_seconds=60,
            require_redis=getattr(settings, "api_rate_limit_require_redis", False),
        )
    except RateLimitUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Rate limiting is temporarily unavailable. Try again later.",
        ) from None
    if not allowed:
        logger.warning(
            "auth refresh rate limit exceeded",
            extra={"client_ip": client_ip, "identifier": identifier},
        )
        raise HTTPException(
            status_code=429,
            detail="Too many refresh requests, please try again later.",
        )
    try:
        tokens = await refresh_tokens(payload.refresh_token, session)
        await session.commit()
        return tokens
    except AuthError as e:
        await session.rollback()
        logger.warning("Refresh token error: %s", e)
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
        ) from e


@router.post("/logout", status_code=204)
async def post_logout(
    user_id_and_jti=Depends(get_current_user_id_and_jti),
    session: AsyncSession = Depends(get_db),
    redis_blocklist=Depends(get_redis_blocklist),
) -> None:
    """
    로그아웃. refresh_token_version 증가 + 현재 Access Token Blocklist 등록(Redis 있을 때).
    Authorization: Bearer <access_token> 필요. 204 No Content.
    """
    user_id, jti = user_id_and_jti
    await logout_user(session, user_id)
    await session.commit()
    if redis_blocklist and jti and settings.jwt_access_expire_seconds > 0:
        try:
            await add_access_to_blocklist(
                redis_blocklist, jti, settings.jwt_access_expire_seconds
            )
        except BlocklistUnavailableError:
            raise HTTPException(
                status_code=503,
                detail="Logout could not revoke token on server; please retry later.",
            ) from None
