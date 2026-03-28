"""Auth API. 구글 OAuth + JWT."""

import hashlib
import logging
import uuid as uuid_mod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, cast

import httpx
import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pyjwt_key_fetcher import AsyncKeyFetcher
from redis.asyncio import Redis as RedisAsyncio
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.core.api_rate_limit import (
    RateLimitUnavailableError,
    check_rate_limit,
)
from app.core.config import settings
from app.core.deps import SessionDep, get_google_key_fetcher, get_httpx_client, get_redis_blocklist
from app.core.ip_hmac import compute_ip_hmac
from app.core.logging_context import set_request_context
from app.core.network import get_client_ip
from app.core.oauth_state import consume_state, generate_state, store_state
from app.core.redis import BlocklistUnavailableError, add_access_to_blocklist
from app.core.user_id_hmac import compute_user_id_hash
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

BearerCredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
RedisBlocklistDep = Annotated[RedisAsyncio | None, Depends(get_redis_blocklist)]
HttpxClientDep = Annotated[httpx.AsyncClient, Depends(get_httpx_client)]
GoogleKeyFetcherDep = Annotated[AsyncKeyFetcher, Depends(get_google_key_fetcher)]

# 캠퍼스·기숙사 등 동일 IP 다수 사용자 환경 안내 (429 시)
RATE_LIMIT_429_DETAIL_SUFFIX = " 같은 네트워크(캠퍼스·기숙사 등)를 쓰는 경우일 수 있습니다. 잠시 후 다시 시도해 주세요."
AUTH_RETRY_AFTER_SECONDS = 60


def _retry_after_headers(seconds: int = AUTH_RETRY_AFTER_SECONDS) -> dict[str, str]:
    return {"Retry-After": str(seconds)}


def _rate_limit_headers() -> dict[str, str]:
    return _retry_after_headers(AUTH_RETRY_AFTER_SECONDS)


def _log_auth_rate_limit_exceeded(request: Request, client_ip: str) -> None:
    """Rate limit 초과 시 IP HMAC·request_id 포함 구조화 로그. 429 발생 전 호출."""
    try:
        ip_hmac_val, ip_hmac_key_version = compute_ip_hmac(client_ip)
    except Exception:
        ip_hmac_val, ip_hmac_key_version = "", "unknown"
    request_id = getattr(request.state, "request_id", None)
    logger.warning(
        "auth rate limit exceeded",
        extra={
            "ip_hmac": ip_hmac_val,
            "ip_hmac_key_version": ip_hmac_key_version,
            "request_id": request_id,
        },
    )


def _auth_rate_limit_dep(
    action: str,
    max_requests_getter: Callable[[], int],
    too_many_detail: str,
) -> Callable[[Request, RedisAsyncio | None], Awaitable[str]]:
    """Auth 전용 rate-limit 의존성 팩토리. client_ip 확인 → 503, 제한 초과 → 429, 통과 시 client_ip 반환."""

    async def _dep(
        request: Request,
        redis_rate: RedisBlocklistDep,
    ) -> str:
        client_ip = get_client_ip(request)
        if client_ip is None:
            raise HTTPException(
                status_code=400,
                detail="Client IP could not be determined; rate limiting requires a valid client identity.",
            )
        identifier = f"auth_{action}:{client_ip}"
        try:
            allowed = await check_rate_limit(
                redis_rate,
                identifier=identifier,
                max_requests=max_requests_getter(),
                window_seconds=60,
                require_redis=settings.api_rate_limit_require_redis,
            )
        except RateLimitUnavailableError:
            raise HTTPException(
                status_code=503,
                detail="Rate limiting is temporarily unavailable. Try again later.",
                headers=_retry_after_headers(),
            ) from None
        if not allowed:
            _log_auth_rate_limit_exceeded(request, client_ip)
            raise HTTPException(
                status_code=429,
                detail=too_many_detail + RATE_LIMIT_429_DETAIL_SUFFIX,
                headers=_rate_limit_headers(),
            )
        return client_ip

    return _dep


def _refresh_token_fingerprint(refresh_token: str) -> str:
    """Rate-limit 식별자용 refresh token 지문(원문 저장/로그 금지)."""
    return hashlib.sha256(refresh_token.strip().encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class VerifiedAccess:
    """검증된 Access JWT에서 추출한 식별자. 하위 의존성에서 요청당 한 번만 검증된다."""

    user_id: uuid_mod.UUID
    jti: str | None


async def get_verified_access(
    credentials: BearerCredentialsDep,
    redis_blocklist: RedisBlocklistDep,
) -> VerifiedAccess:
    """Bearer Access JWT 검증 후 user_id·jti. Blocklist/Redis 장애 정책. 성공 시 user_id_hash·Sentry 설정."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization")
    try:
        payload = await verify_access_token(
            credentials.credentials,
            redis_blocklist,
            fail_closed=settings.redis.redis_blocklist_fail_closed,
        )
        user_id = uuid_mod.UUID(payload["sub"])
        try:
            user_id_hash = compute_user_id_hash(user_id)
            set_request_context(user_id_hash=user_id_hash)
            sentry_sdk.set_user({"id": user_id_hash})
        except Exception:
            logger.debug("user_id_hash/Sentry set_user failed; continuing.", exc_info=True)
        return VerifiedAccess(user_id=user_id, jti=payload.get("jti"))
    except (AuthError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    except BlocklistUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Authentication service temporarily unavailable",
            headers=_retry_after_headers(),
        ) from None


VerifiedAccessDep = Annotated[VerifiedAccess, Depends(get_verified_access)]


async def get_current_user_id(access: VerifiedAccessDep) -> uuid_mod.UUID:
    """Bearer Access JWT 검증 후 user_id(UUID) 반환."""
    return access.user_id


async def get_current_user_id_and_jti(access: VerifiedAccessDep) -> tuple[uuid_mod.UUID, str | None]:
    """Access JWT 검증 후 (user_id UUID, jti) 반환. 로그아웃 Blocklist 등록용."""
    return access.user_id, access.jti


GoogleStateClientIpDep = Annotated[
    str,
    Depends(
        _auth_rate_limit_dep(
            "google_state",
            lambda: settings.auth_google_state_rate_limit_per_minute,
            "Too many state issuance requests, please try again later.",
        )
    ),
]
GoogleAuthClientIpDep = Annotated[
    str,
    Depends(
        _auth_rate_limit_dep(
            "google",
            lambda: settings.auth_google_rate_limit_per_minute,
            "Too many authentication attempts, please try again later.",
        )
    ),
]
RefreshClientIpDep = Annotated[
    str,
    Depends(
        _auth_rate_limit_dep(
            "refresh",
            lambda: settings.auth_refresh_rate_limit_per_minute,
            "Too many refresh requests, please try again later.",
        )
    ),
]
CurrentUserIdAndJtiDep = Annotated[tuple[uuid_mod.UUID, str | None], Depends(get_current_user_id_and_jti)]


@router.get("/google/state")
async def get_google_auth_state(
    redis_blocklist: RedisBlocklistDep,
    client_ip: GoogleStateClientIpDep,
) -> dict[str, str]:
    """
    로그인 시작 시 1회용 state 발급. Redis에 저장 후 반환. CSRF 방어용.
    IP 기반 rate limit 적용. Redis 미설정 시 503.
    """
    if redis_blocklist is None:
        raise HTTPException(
            status_code=503,
            detail="State storage temporarily unavailable",
            headers=_retry_after_headers(),
        )
    state = generate_state()
    stored = await store_state(cast(Any, redis_blocklist), state)
    if not stored:
        raise HTTPException(
            status_code=503,
            detail="State storage temporarily unavailable",
            headers=_retry_after_headers(),
        )
    return {"state": state}


@router.post("/google", response_model=TokenResponse)
async def post_google_auth(
    payload: TokenPayload,
    session: SessionDep,
    http_client: HttpxClientDep,
    key_fetcher: GoogleKeyFetcherDep,
    redis_blocklist: RedisBlocklistDep,
    client_ip: GoogleAuthClientIpDep,
) -> TokenResponse:
    """
    구글 OAuth Authorization Code로 로그인.
    code를 받아 검증 후 Access/Refresh JWT 반환.
    production에서는 state 필수(CSRF 방어). 외부 API 장애 → 503, 클라이언트 인증 오류 → 400.
    """
    is_production = (settings.environment or "").strip().lower() == "production"
    if is_production and (payload.state is None or not (payload.state or "").strip()):
        raise HTTPException(
            status_code=400,
            detail="state is required in production for CSRF protection",
        )
    if payload.state is not None:
        if redis_blocklist is None:
            raise HTTPException(
                status_code=503,
                detail="State validation temporarily unavailable",
                headers=_retry_after_headers(),
            )
        consumed = await consume_state(cast(Any, redis_blocklist), payload.state)
        if not consumed:
            raise HTTPException(
                status_code=400,
                detail="Invalid or already used state",
            )
    try:
        result = await google_login(
            session,
            payload.code,
            redirect_uri=payload.redirect_uri,
            http_client=http_client,
            key_fetcher=key_fetcher,
            client_ip=client_ip,
            code_verifier=payload.code_verifier,
        )
        await session.commit()
        return TokenResponse(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            token_type=result.token_type,
            expires_in=result.expires_in,
        )
    except AuthServiceUnavailableError as e:
        logger.warning("Google auth unavailable: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Authentication service temporarily unavailable",
            headers=_retry_after_headers(),
        ) from e
    except AuthError as e:
        logger.warning("Google login auth error: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Invalid request",
        ) from e
    except (OperationalError, SQLAlchemyTimeoutError, TimeoutError) as e:
        await session.rollback()
        logger.warning(
            "Google auth DB temporarily unavailable: %s",
            type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail="Authentication service temporarily unavailable",
            headers=_retry_after_headers(),
        ) from e
    except Exception:
        await session.rollback()
        raise


@router.post("/refresh", response_model=TokenResponse)
async def post_refresh(
    request: Request,
    payload: RefreshTokenPayload,
    session: SessionDep,
    client_ip: RefreshClientIpDep,
    redis_rate: RedisBlocklistDep,
) -> TokenResponse:
    """
    Refresh 토큰으로 새 Access/Refresh JWT 발급.
    type=refresh, token_version 검증 후 새 쌍 반환. 무효화된 토큰 시 401.
    """
    token_fp = _refresh_token_fingerprint(payload.refresh_token)
    identifier = f"auth_refresh_fp:{token_fp}"
    try:
        allowed = await check_rate_limit(
            redis_rate,
            identifier=identifier,
            max_requests=settings.auth_refresh_token_fingerprint_rate_limit_per_minute,
            window_seconds=60,
            require_redis=settings.api_rate_limit_require_redis,
        )
    except RateLimitUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Rate limiting is temporarily unavailable. Try again later.",
            headers=_retry_after_headers(),
        ) from None
    if not allowed:
        _log_auth_rate_limit_exceeded(request, client_ip)
        raise HTTPException(
            status_code=429,
            detail="Too many refresh requests, please try again later." + RATE_LIMIT_429_DETAIL_SUFFIX,
            headers=_rate_limit_headers(),
        )

    try:
        result = await refresh_tokens(payload.refresh_token, session)
        await session.commit()
        return TokenResponse(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            token_type=result.token_type,
            expires_in=result.expires_in,
        )
    except AuthError as e:
        await session.rollback()
        logger.warning("Refresh token error: %s", e)
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
        ) from e
    except Exception:
        await session.rollback()
        raise


@router.post("/logout", status_code=204, response_model=None)
async def post_logout(
    session: SessionDep,
    user_id_and_jti: CurrentUserIdAndJtiDep,
    redis_blocklist: RedisBlocklistDep,
) -> None:
    """
    로그아웃. Redis Blocklist 등록(성공) 후 refresh_token_version 증가 + commit.
    Redis 먼저 등록해 두어, DB 실패 시에도 Access는 이미 블록됨.
    Authorization: Bearer <access_token> 필요. 204 No Content.
    """
    user_id, jti = user_id_and_jti
    if redis_blocklist and jti and settings.jwt_access_expire_seconds > 0:
        try:
            await add_access_to_blocklist(redis_blocklist, jti, settings.jwt_access_expire_seconds)
        except BlocklistUnavailableError:
            raise HTTPException(
                status_code=503,
                detail="Logout could not revoke token on server; please retry later.",
                headers=_retry_after_headers(),
            ) from None
    try:
        await logout_user(session, user_id)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
