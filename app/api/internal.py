"""
내부 전용 API (Cron·관리). 보안 키는 Header만 허용(X-Crawl-Trigger-Secret 또는 Authorization: Bearer).
Query 파라미터 시크릿 미지원(Access Log 유출 방지). college별 분산락으로 중복 enqueue 방지.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from redis.asyncio import Redis as RedisAsyncio

from app.core import metrics
from app.core.api_rate_limit import (
    RateLimitUnavailableError,
    check_rate_limit,
)
from app.core.config import settings
from app.core.deps import (
    ReadOnlySessionDep,
    get_crawl_stats_service,
    get_internal_crawl_service,
    get_redis_trigger_lock,
)
from app.core.internal_auth import (
    CrawlTriggerNotConfiguredError,
    InvalidCrawlTriggerSecretError,
    check_crawl_trigger_secret,
)
from app.core.ip_hmac import compute_ip_hmac
from app.core.network import get_client_ip
from app.core.read_cache import (
    get_cached_with_soft_ttl,
    release_cached_lock,
    set_cached_with_soft_ttl,
    wait_for_cached,
)
from app.domain.contracts.internal_contracts import (
    TriggerCrawlCmd,
    TriggerCrawlResult,
    TriggerCrawlResultKind,
)
from app.schemas.internal import CrawlRunStatsItem, CrawlStatsResponse
from app.services.crawl_stats_service import CrawlStatsService

router = APIRouter(prefix="/internal", tags=["internal"])
logger = logging.getLogger(__name__)

RATE_LIMIT_RETRY_AFTER_SECONDS = 60


def _map_result_to_status(result: TriggerCrawlResult) -> int:
    """TriggerCrawlResult.result_kind에 따라 HTTP status code 반환. Router 전용."""
    if result.result_kind == TriggerCrawlResultKind.cached:
        return 202
    if result.result_kind == TriggerCrawlResultKind.success:
        return 200
    return 503  # partial_failure, infra_unavailable


def _rate_limit_headers() -> dict[str, str]:
    return {"Retry-After": str(RATE_LIMIT_RETRY_AFTER_SECONDS)}


def _rate_limit_identity(request: Request) -> str:
    """
    pre-auth rate limit용 식별자.
    get_client_ip가 없으면 direct peer host, 그것도 없으면 unknown 사용.
    """
    ip = get_client_ip(request)
    if ip:
        return ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def _enforce_rate_limit_or_503(
    redis_client: RedisAsyncio | None,
    *,
    identifier: str,
    max_requests: int,
) -> bool:
    """공통 rate limit 검사. 백엔드 장애 시 503으로 fail-closed."""
    try:
        return await check_rate_limit(
            redis_client,
            identifier=identifier,
            max_requests=max_requests,
            window_seconds=60,
            require_redis=settings.api_rate_limit_require_redis,
        )
    except RateLimitUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Rate limiting is temporarily unavailable. Try again later.",
        ) from None


def _log_internal_auth_failure(
    request: Request,
    reason: str,
    error: Exception | None = None,
) -> None:
    """구조화 로그로 내부 인증 실패 기록. 시크릿 값·평문 IP는 로깅하지 않으며, IP는 HMAC만 기록."""
    endpoint = getattr(request.url, "path", "unknown") if request else "unknown"
    metrics.increment(
        metrics.INTERNAL_AUTH_FAILED_TOTAL,
        labels={"endpoint": endpoint, "reason": reason},
    )
    client_ip = get_client_ip(request) if request else None
    try:
        ip_hmac_val, ip_hmac_key_version = compute_ip_hmac(client_ip or "")
    except Exception:
        ip_hmac_val, ip_hmac_key_version = "", "unknown"
    request_id = getattr(request.state, "request_id", None) if request else None
    extra = {
        "path": endpoint,
        "ip_hmac": ip_hmac_val or "(no key)",
        "ip_hmac_key_version": ip_hmac_key_version,
        "request_id": request_id,
        "reason": reason,
    }
    if error is not None:
        logger.warning("internal auth failed", extra=extra, exc_info=error)
    else:
        logger.warning("internal auth failed", extra=extra)


def _authorize_internal_trigger(
    request: Request,
    x_crawl_trigger_secret: str | None,
    authorization: str | None,
) -> None:
    """내부 트리거 시크릿 검사. 실패 시 HTTPException 발생."""
    try:
        check_crawl_trigger_secret(x_crawl_trigger_secret, authorization)
    except CrawlTriggerNotConfiguredError as e:
        _log_internal_auth_failure(request, reason="trigger_not_configured", error=e)
        raise HTTPException(
            status_code=503,
            detail="Crawl trigger not configured (CRAWL_TRIGGER_SECRET missing)",
        ) from None
    except InvalidCrawlTriggerSecretError as e:
        _log_internal_auth_failure(request, reason="invalid_or_missing_secret", error=e)
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing crawl trigger secret",
        ) from None


def _require_client_ip(request: Request, *, endpoint: str) -> str:
    """Fail-closed: if client IP cannot be resolved, return 503."""
    client_ip = get_client_ip(request)
    if client_ip is None:
        raise HTTPException(
            status_code=503,
            detail=f"Client IP could not be determined for {endpoint}",
        )
    return client_ip


async def _apply_internal_preauth_limit(
    request: Request,
    redis_client: RedisAsyncio | None,
    *,
    endpoint: str,
) -> None:
    identity = _rate_limit_identity(request)
    allowed = await _enforce_rate_limit_or_503(
        redis_client,
        identifier=f"internal_preauth:{endpoint}:{identity}",
        max_requests=settings.internal_preauth_rate_limit_per_minute,
    )
    if allowed:
        return
    metrics.increment(
        metrics.INTERNAL_PREAUTH_RATE_LIMITED_TOTAL,
        labels={"endpoint": endpoint},
    )
    raise HTTPException(
        status_code=429,
        detail="Too many internal requests, please try again later.",
        headers=_rate_limit_headers(),
    )


async def _authorize_with_fail_limit(
    request: Request,
    redis_client: RedisAsyncio | None,
    *,
    endpoint: str,
    x_crawl_trigger_secret: str | None,
    authorization: str | None,
) -> None:
    try:
        _authorize_internal_trigger(request, x_crawl_trigger_secret, authorization)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        identity = _rate_limit_identity(request)
        allowed = await _enforce_rate_limit_or_503(
            redis_client,
            identifier=f"internal_auth_fail:{endpoint}:{identity}",
            max_requests=settings.internal_auth_fail_rate_limit_per_minute,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many internal authentication failures, please try again later.",
                headers=_rate_limit_headers(),
            ) from None
        raise


@router.post("/trigger-crawl")
async def post_trigger_crawl(
    request: Request,
    college_code: str | None = Query(
        None,
        description="단과대 코드(engineering, science, ...). 없으면 전체 순차 enqueue.",
    ),
    x_crawl_trigger_secret: str | None = Header(None, alias="X-Crawl-Trigger-Secret"),
    authorization: str | None = Header(None),
    idempotency_key: str | None = Header(
        None,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
    redis_client: RedisAsyncio | None = Depends(get_redis_trigger_lock),
    internal_crawl_service=Depends(get_internal_crawl_service),
):
    """
    크롤 태스크 enqueue. 보안 키는 Header만 필수. college별 Redis 분산락(SET NX EX)으로 중복 enqueue 방지.
    Idempotency-Key 있으면 동일 키 재요청 시 202 + 캐시된 결과. 부분 실패 시에도 200으로 enqueued/skipped/failed 반환.
    P1: 인증 후 rate-limit 적용. 식별자는 get_client_ip(프록시 대응) 사용.
    """
    endpoint = "/internal/trigger-crawl"
    await _apply_internal_preauth_limit(request, redis_client, endpoint=endpoint)
    await _authorize_with_fail_limit(
        request,
        redis_client,
        endpoint=endpoint,
        x_crawl_trigger_secret=x_crawl_trigger_secret,
        authorization=authorization,
    )
    client_ip = _require_client_ip(request, endpoint="/internal/trigger-crawl")
    rate_identifier = f"internal_trigger_crawl:{client_ip}"
    allowed = await _enforce_rate_limit_or_503(
        redis_client,
        identifier=rate_identifier,
        max_requests=settings.internal_trigger_crawl_rate_limit_per_minute,
    )
    if not allowed:
        _log_internal_auth_failure(
            request,
            reason="rate_limited_trigger_crawl",
            error=None,
        )
        raise HTTPException(
            status_code=429,
            detail="Too many internal trigger requests, please try again later.",
            headers=_rate_limit_headers(),
        )

    key_stripped = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
    cmd = TriggerCrawlCmd(
        college_code=college_code,
        idempotency_key=key_stripped,
        client_ip=client_ip,
    )
    result = await internal_crawl_service.trigger(cmd)
    status_code = _map_result_to_status(result)
    return JSONResponse(status_code=status_code, content=result.payload)


@router.get("/crawl-stats")
async def get_crawl_stats(
    request: Request,
    session: ReadOnlySessionDep,
    limit: int = Query(50, ge=1, le=200, description="최근 N건"),
    x_crawl_trigger_secret: str | None = Header(None, alias="X-Crawl-Trigger-Secret"),
    authorization: str | None = Header(None),
    redis_client: RedisAsyncio | None = Depends(get_redis_trigger_lock),
    crawl_stats_service: CrawlStatsService = Depends(get_crawl_stats_service),
) -> CrawlStatsResponse:
    """
    최근 크롤 실행 이력. 단과대별 last_run_at, status, notices_upserted, has_error.
    보안 키 필수. Header만 사용 (X-Crawl-Trigger-Secret 또는 Authorization: Bearer).
    인증 실패 시 공통 _authorize_internal_trigger 로깅/응답으로 감사 추적 일관성 유지.
    P1: 인증 후 rate-limit. 식별자는 get_client_ip(프록시 대응) 사용.
    """
    endpoint = "/internal/crawl-stats"
    await _apply_internal_preauth_limit(request, redis_client, endpoint=endpoint)
    await _authorize_with_fail_limit(
        request,
        redis_client,
        endpoint=endpoint,
        x_crawl_trigger_secret=x_crawl_trigger_secret,
        authorization=authorization,
    )
    client_ip = _require_client_ip(request, endpoint="/internal/crawl-stats")
    rate_identifier = f"internal_crawl_stats:{client_ip}"
    allowed = await _enforce_rate_limit_or_503(
        redis_client,
        identifier=rate_identifier,
        max_requests=settings.internal_crawl_stats_rate_limit_per_minute,
    )
    if not allowed:
        _log_internal_auth_failure(
            request,
            reason="rate_limited_crawl_stats",
            error=None,
        )
        raise HTTPException(
            status_code=429,
            detail="Too many internal stats requests, please try again later.",
            headers=_rate_limit_headers(),
        )
    state = getattr(request.app.state, "operational_mode", "NORMAL")
    key_parts = ("crawl_stats", str(limit))
    cached, should_refresh, lock_token = await get_cached_with_soft_ttl(redis_client, *key_parts)

    # Fresh hit: 즉시 반환
    if cached is not None and not should_refresh:
        metrics.increment(metrics.READ_CACHE_FRESH_HIT_TOTAL)
        return CrawlStatsResponse.model_validate(cached)

    # Stale + lock 미획득: stale 즉시 반환
    if cached is not None and should_refresh and lock_token is None:
        metrics.increment(metrics.READ_CACHE_STALE_HIT_TOTAL)
        return CrawlStatsResponse.model_validate(cached)

    # Hard miss + lock 미획득: 짧게 wait 후 재조회
    if cached is None and lock_token is None:
        metrics.increment(metrics.READ_CACHE_WAIT_TOTAL)
        wait_ms = getattr(settings, "read_cache_wait_for_fresh_ms", 1000)
        cached, should_refresh, lock_token = await wait_for_cached(redis_client, wait_ms, *key_parts)
        if cached is not None:
            return CrawlStatsResponse.model_validate(cached)
        if state == "DEGRADED":
            raise HTTPException(
                status_code=503,
                detail="Service degraded; cached data unavailable. Try again later.",
                headers={"Retry-After": "60"},
            )
        # 재조회 후에도 miss면 한 번 더 락 획득 시도. 성공 시에만 refresh, 실패 시 503(stampede 방지)
        cached, should_refresh, lock_token = await get_cached_with_soft_ttl(redis_client, *key_parts)
        if cached is not None:
            return CrawlStatsResponse.model_validate(cached)
        if lock_token is None:
            raise HTTPException(
                status_code=503,
                detail="Cache unavailable; try again later.",
                headers={"Retry-After": "2"},
            )

    # should_refresh && lock_token 있음: DB 조회 후 갱신 (락 없이 DB 직접 치는 경로 제거)
    if should_refresh and lock_token is not None:
        metrics.increment(metrics.READ_CACHE_MISS_TOTAL if cached is None else metrics.READ_CACHE_STALE_HIT_TOTAL)
        metrics.increment(metrics.READ_CACHE_REFRESH_TOTAL)
        result = await crawl_stats_service.get_crawl_stats(session, limit=limit)
        response = CrawlStatsResponse(
            runs=[
                CrawlRunStatsItem(
                    college_code=r.college_code,
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                    status=r.status,
                    notices_upserted=r.notices_upserted,
                    has_error=r.has_error,
                )
                for r in result.runs
            ],
            limit=result.limit,
        )
        await set_cached_with_soft_ttl(redis_client, *key_parts, value=response.model_dump())
        await release_cached_lock(redis_client, *key_parts, token=lock_token)
        return response

    if cached is not None:
        return CrawlStatsResponse.model_validate(cached)
    raise HTTPException(
        status_code=503,
        detail="Service degraded; cached data unavailable. Try again later.",
        headers={"Retry-After": "60"},
    )


def _metrics_allowed_client_ip(request: Request) -> bool:
    """
    METRICS_ALLOWED_IPS가 설정된 경우 해당 IP만 허용. 미설정(빈 값) 시 모든 IP 차단(fail-closed).
    프록시 환경: get_client_ip 사용으로 X-Forwarded-For + trusted_proxy 검사 후 실제 클라이언트 IP로
    allowlist 검사. request.client.host만 쓰면 프록시 IP 하나로 통과되어 외부 트래픽이 우회할 수 있음.
    """
    allowed_ips_str = (settings.metrics_allowed_ips or "").strip() or ""
    if not allowed_ips_str.strip():
        return False
    allowed = {ip.strip() for ip in allowed_ips_str.split(",") if ip.strip()}
    client_ip = get_client_ip(request)
    if client_ip is None:
        return False
    return client_ip in allowed


@router.get("/metrics")
async def get_metrics(request: Request) -> Response:
    """Prometheus 텍스트 포맷으로 메트릭 노출. METRICS_ALLOWED_IPS 미설정(빈 값) 시 모든 IP 차단(fail-closed)."""
    if not _metrics_allowed_client_ip(request):
        raise HTTPException(status_code=403, detail="Metrics access not allowed for this client")
    data = metrics.get_all()
    lines: list[str] = []
    for name, val in data["counters"].items():
        lines.append(f"{name} {val}")
    for name, val in data["gauges"].items():
        lines.append(f"{name} {val}")
    return Response(content="\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")
