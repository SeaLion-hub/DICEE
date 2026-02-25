"""Auth API. 구글 OAuth + JWT."""

import ipaddress
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.api_rate_limit import check_rate_limit
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_google_key_fetcher, get_httpx_client, get_redis_blocklist
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


# X-Forwarded-For 역순 훑기: 최대 IP 개수. 초과 시 request.client.host 사용.
_XFF_MAX_IPS = 32

# RFC 1918 사설 대역 + IPv6 private/loopback. 후보 IP가 여기 있으면 클라이언트 IP로 사용하지 않고 fallback.
def _is_private_ip(ip: str) -> bool:
    if not ip or not ip.strip():
        return True
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        # 파싱 실패 시 보수적으로 private 처리하여 fallback을 사용.
        return True
    if addr.is_private or addr.is_loopback:
        return True
    return False


def _client_ip_from_request(request: Request) -> str | None:
    """
    클라이언트 IP. 역순 훑기: X-Forwarded-For를 오른쪽→왼쪽으로 훑어 신뢰 목록에 없는 첫 IP 채택.
    직전 피어가 trusted가 아니면 request.client.host만 사용. RFC 1918 후보는 fallback.
    """
    if not request.client:
        return None
    fallback = request.client.host
    trusted = settings.trusted_proxy_ips_set
    if request.client.host not in trusted:
        return fallback
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded or not forwarded.strip():
        return fallback
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if len(parts) > _XFF_MAX_IPS:
        return fallback
    for ip in reversed(parts):
        if ip not in trusted:
            if _is_private_ip(ip):
                return fallback
            return ip
    return parts[0] if parts else fallback


@router.post("/google", response_model=TokenResponse)
async def post_google_auth(
    request: Request,
    payload: TokenPayload,
    http_client: httpx.AsyncClient = Depends(get_httpx_client),
    key_fetcher=Depends(get_google_key_fetcher),
    redis_rate=Depends(get_redis_blocklist),
) -> TokenResponse:
    """
    구글 OAuth Authorization Code로 로그인.
    code를 받아 검증 후 Access/Refresh JWT 반환.
    외부 API 장애(타임아웃 등) → 503, 클라이언트 인증 오류 → 400.
    """
    client_ip = _client_ip_from_request(request) or "unknown"
    identifier = f"auth_google:{client_ip}"
    allowed = await check_rate_limit(
        redis_rate,
        identifier=identifier,
        max_requests=getattr(settings, "auth_google_rate_limit_per_minute", 10),
        window_seconds=60,
    )
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
        return await google_login(
            code=payload.code,
            redirect_uri=payload.redirect_uri,
            http_client=http_client,
            key_fetcher=key_fetcher,
            client_ip=client_ip,
        )
    except AuthServiceUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/refresh", response_model=TokenResponse)
async def post_refresh(
    request: Request,
    payload: RefreshTokenPayload,
    session=Depends(get_db),
    redis_rate=Depends(get_redis_blocklist),
) -> TokenResponse:
    """
    Refresh 토큰으로 새 Access/Refresh JWT 발급.
    type=refresh, token_version 검증 후 새 쌍 반환. 무효화된 토큰 시 401.
    """
    client_ip = _client_ip_from_request(request) or "unknown"
    identifier = f"auth_refresh:{client_ip}"
    allowed = await check_rate_limit(
        redis_rate,
        identifier=identifier,
        max_requests=getattr(settings, "auth_refresh_rate_limit_per_minute", 60),
        window_seconds=60,
    )
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
        return await refresh_tokens(payload.refresh_token, session)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


@router.post("/logout", status_code=204)
async def post_logout(
    user_id_and_jti=Depends(get_current_user_id_and_jti),
    redis_blocklist=Depends(get_redis_blocklist),
) -> None:
    """
    로그아웃. refresh_token_version 증가 + 현재 Access Token Blocklist 등록(Redis 있을 때).
    Authorization: Bearer <access_token> 필요. 204 No Content.
    """
    user_id, jti = user_id_and_jti
    await logout_user(
        user_id,
        access_jti=jti,
        ttl_seconds=settings.jwt_access_expire_seconds,
        redis_blocklist_client=redis_blocklist,
    )
