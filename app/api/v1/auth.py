"""Auth API. 구글 OAuth + JWT."""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.deps import get_google_key_fetcher, get_httpx_client, get_redis_blocklist
from app.schemas.auth import TokenPayload, TokenResponse
from app.services.auth_service import (
    AuthError,
    AuthServiceUnavailableError,
    google_login,
    logout_user,
    verify_access_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
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


def _client_ip_from_request(request: Request) -> str | None:
    """
    클라이언트 IP. 명세 3.2: 평문은 DB에 저장하지 않고 ip_hmac만 저장.
    직전 피어(request.client.host)가 TRUSTED_PROXY_IPS에 있을 때만 X-Forwarded-For 첫 값을 사용.
    목록에 없거나 비어 있으면 X-Forwarded-For를 신뢰하지 않고 request.client.host만 반환.
    """
    trusted = settings.trusted_proxy_ips_set
    if request.client and request.client.host in trusted:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.post("/google", response_model=TokenResponse)
async def post_google_auth(
    request: Request,
    payload: TokenPayload,
    http_client: httpx.AsyncClient = Depends(get_httpx_client),
    key_fetcher=Depends(get_google_key_fetcher),
) -> TokenResponse:
    """
    구글 OAuth Authorization Code로 로그인.
    code를 받아 검증 후 Access/Refresh JWT 반환.
    외부 API 장애(타임아웃 등) → 503, 클라이언트 인증 오류 → 400.
    """
    try:
        return await google_login(
            code=payload.code,
            redirect_uri=payload.redirect_uri,
            http_client=http_client,
            key_fetcher=key_fetcher,
            client_ip=_client_ip_from_request(request),
        )
    except AuthServiceUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
