"""
내부 전용 API (Cron·관리). 보안 키는 Header만 허용(X-Crawl-Trigger-Secret 또는 Authorization: Bearer).
Query 파라미터 시크릿 미지원(Access Log 유출 방지). college별 분산락으로 중복 enqueue 방지.
"""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from redis.asyncio import Redis as RedisAsyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_rate_limit import check_rate_limit
from app.core.config import settings
from app.core.crawler_config import COLLEGE_CODE_TO_MODULE
from app.core.database import get_db
from app.core.deps import get_redis_trigger_lock
from app.core.ip_hmac import compute_ip_hmac
from app.core.internal_auth import (
    CrawlTriggerNotConfiguredError,
    InvalidCrawlTriggerSecretError,
    check_crawl_trigger_secret,
)
from app.core.redis import (
    RedisLockUnavailableError,
    acquire_trigger_lock,
    get_trigger_idempotency_result,
    release_trigger_lock,
    set_trigger_idempotency_result,
    try_claim_trigger_idempotency,
)
from app.core import metrics
from app.repositories.crawl_run_repository import get_recent_crawl_runs

router = APIRouter(prefix="/internal", tags=["internal"])
logger = logging.getLogger(__name__)

# 단과대별 크롤 시작 시간 분산(Thundering Herd 방지). 초 단위. 예: 300 = 5분 간격.
CRAWL_STAGGER_SECONDS = 300


def _log_internal_auth_failure(
    request: Request,
    reason: str,
    error: Exception | None = None,
) -> None:
    """구조화 로그로 내부 인증 실패 기록. 시크릿 값·평문 IP는 로깅하지 않으며, IP는 HMAC만 기록."""
    client_ip = request.client.host if request and request.client else None
    ip_hmac_val, ip_hmac_key_version = compute_ip_hmac(client_ip or "")
    request_id = getattr(request.state, "request_id", None) if request else None
    extra = {
        "path": getattr(request.url, "path", None) if request else None,
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


def _resolve_college_codes(college_code: str | None) -> list[str]:
    """college_code 정규화·검증 후 코드 목록 반환. 단일 코드 미등록 시 HTTPException(400)."""
    normalized = college_code.strip() if college_code and college_code.strip() else None
    if normalized and normalized not in COLLEGE_CODE_TO_MODULE:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown college_code: {normalized}. Valid: {list(COLLEGE_CODE_TO_MODULE.keys())}",
        )
    return [normalized] if normalized else list(COLLEGE_CODE_TO_MODULE.keys())


async def _claim_idempotency(
    redis_client: RedisAsyncio | None,
    idempotency_key: str | None,
    scope: str,
) -> tuple[bool, dict | None]:
    """
    Idempotency 슬롯 점유 시도. 반환 (claimed, cached_or_none).
    claimed=True면 이번 요청이 처리 담당. claimed=False면 cached에 202 응답용 payload(캐시 결과 또는 in_progress).
    """
    if not idempotency_key or redis_client is None:
        return (True, None)
    claimed = await try_claim_trigger_idempotency(redis_client, idempotency_key, scope)
    if claimed:
        return (True, None)
    cached = await get_trigger_idempotency_result(redis_client, idempotency_key, scope)
    if cached is not None:
        return (False, cached)
    return (False, {"detail": "in_progress", "code": "IDEMPOTENCY_IN_PROGRESS"})


async def _enqueue_crawls(
    request: Request,
    redis_client: RedisAsyncio | None,
    codes: list[str],
) -> tuple[dict, int]:
    """크롤 태스크 enqueue. 반환 (응답 body, status_code)."""
    from app.services.tasks import crawl_college_task

    status_code = 200
    out: dict = {}
    task_ids: list[dict] = []
    skipped: list[str] = []
    failed: list[str] = []
    for i, code in enumerate(codes):
        lock_token: str | None = None
        if redis_client is not None:
            try:
                acquired, lock_token = await acquire_trigger_lock(redis_client, code)
            except RedisLockUnavailableError:
                logger.exception("Trigger lock unavailable (Redis error) for college=%s", code)
                status_code = 503
                out = {
                    "detail": "Service temporarily unavailable",
                    "code": "REDIS_LOCK_UNAVAILABLE",
                }
                break
            if not acquired:
                skipped.append(code)
                continue
        countdown = i * CRAWL_STAGGER_SECONDS if len(codes) > 1 else 0
        enqueued_at = time.time()
        try:
            result = await asyncio.to_thread(
                crawl_college_task.apply_async,
                args=[code, lock_token],
                kwargs={"enqueued_at": enqueued_at},
                countdown=countdown,
            )
        except Exception:
            logger.exception("trigger-crawl apply_async failed: code=%s", code)
            if redis_client is not None and lock_token:
                await release_trigger_lock(redis_client, code, lock_token)
            failed.append(code)
            continue
        task_ids.append({"college_code": code, "task_id": result.id, "countdown_sec": countdown})
        request_id = getattr(request.state, "request_id", None) if request else None
        logger.info(
            "trigger-crawl enqueued: college_code=%s task_id=%s countdown=%s request_id=%s",
            code, result.id, countdown, request_id,
        )
    if status_code == 200:
        out = {"enqueued": len(task_ids), "tasks": task_ids}
        if skipped:
            out["skipped"] = skipped
        if failed:
            out["failed"] = failed
    return (out, status_code)


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
):
    """
    크롤 태스크 enqueue. 보안 키는 Header만 필수. college별 Redis 분산락(SET NX EX)으로 중복 enqueue 방지.
    Idempotency-Key 있으면 동일 키 재요청 시 202 + 캐시된 결과. 부분 실패 시에도 200으로 enqueued/skipped/failed 반환.
    """
    client_ip = request.client.host if request and request.client else "unknown"
    rate_identifier = f"internal_trigger_crawl:{client_ip}"
    allowed = await check_rate_limit(
        redis_client,
        identifier=rate_identifier,
        max_requests=getattr(settings, "internal_trigger_crawl_rate_limit_per_minute", 30),
        window_seconds=60,
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
        )
    _authorize_internal_trigger(request, x_crawl_trigger_secret, authorization)

    codes = _resolve_college_codes(college_code)
    idempotency_scope = codes[0] if len(codes) == 1 else "all"
    key_stripped = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None

    claimed, cached = await _claim_idempotency(redis_client, key_stripped, idempotency_scope)
    if not claimed:
        return JSONResponse(status_code=202, content=cached or {})

    if redis_client is None and getattr(settings, "redis_trigger_lock_required", False):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Service temporarily unavailable",
                "code": "REDIS_LOCK_UNAVAILABLE",
            },
        )

    out: dict = {}
    status_code = 500
    try:
        out, status_code = await _enqueue_crawls(request, redis_client, codes)
    finally:
        should_cache = (
            claimed
            and redis_client is not None
            and key_stripped
            and 200 <= status_code < 500
            and bool(out)
        )
        if should_cache:
            await set_trigger_idempotency_result(
                redis_client, key_stripped, idempotency_scope, out
            )
    return JSONResponse(status_code=status_code, content=out)


@router.get("/crawl-stats")
async def get_crawl_stats(
    request: Request,
    limit: int = Query(50, ge=1, le=200, description="최근 N건"),
    x_crawl_trigger_secret: str | None = Header(None, alias="X-Crawl-Trigger-Secret"),
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """
    최근 크롤 실행 이력. 단과대별 last_run_at, status, notices_upserted, has_error.
    보안 키 필수. Header만 사용 (X-Crawl-Trigger-Secret 또는 Authorization: Bearer).
    """
    client_ip = request.client.host if request and request.client else "unknown"
    rate_identifier = f"internal_crawl_stats:{client_ip}"
    # crawl-stats는 운영자용이라 조금 더 완화된 제한을 둔다.
    allowed = await check_rate_limit(
        None,  # Redis Trigger Lock과 별개로 간단한 인메모리 제한만 사용
        identifier=rate_identifier,
        max_requests=getattr(settings, "internal_crawl_stats_rate_limit_per_minute", 60),
        window_seconds=60,
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
        )
    try:
        check_crawl_trigger_secret(x_crawl_trigger_secret, authorization)
    except CrawlTriggerNotConfiguredError as e:
        # Request 객체는 Depends로 주입되지 않으므로 로깅 없이 HTTP 오류만 변환
        raise HTTPException(
            status_code=503,
            detail="Crawl trigger not configured (CRAWL_TRIGGER_SECRET missing)",
        ) from None
    except InvalidCrawlTriggerSecretError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing crawl trigger secret",
        ) from None
    runs = await get_recent_crawl_runs(session, limit=limit)
    sanitized: list[dict] = []
    for run in runs:
        # 원본 error_message는 응답에서 제거하고, has_error로만 실패 여부를 노출.
        item = {k: v for k, v in run.items() if k != "error_message"}
        item["has_error"] = bool(run.get("error_message"))
        sanitized.append(item)
    return {"runs": sanitized, "limit": limit}


def _metrics_allowed_client_ip(request: Request) -> bool:
    """METRICS_ALLOWED_IPS가 설정된 경우 해당 IP만 허용. 미설정 시 모든 IP 허용."""
    allowed_ips_str = getattr(settings, "metrics_allowed_ips", "") or ""
    if not allowed_ips_str.strip():
        return True
    allowed = {ip.strip() for ip in allowed_ips_str.split(",") if ip.strip()}
    client_ip = request.client.host if request and request.client else ""
    return client_ip in allowed


@router.get("/metrics")
async def get_metrics(request: Request) -> Response:
    """Prometheus 텍스트 포맷으로 메트릭 노출. METRICS_ALLOWED_IPS 설정 시 해당 IP만 허용."""
    if not _metrics_allowed_client_ip(request):
        raise HTTPException(status_code=403, detail="Metrics access not allowed for this client")
    data = metrics.get_all()
    lines: list[str] = []
    for name, val in data["counters"].items():
        lines.append(f"{name} {val}")
    for name, val in data["gauges"].items():
        lines.append(f"{name} {val}")
    return Response(content="\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")
