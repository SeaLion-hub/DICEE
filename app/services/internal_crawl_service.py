"""
내부 API 트리거 크롤 서비스. 멱등성·락·enqueue 오케스트레이션.
도메인 결과(TriggerCrawlResult) 또는 도메인 예외 단위의 트랜잭션을 처리합니다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from redis.asyncio import Redis as RedisAsyncio

from app.core.config import settings
from app.core.crawler_config import COLLEGE_CODE_TO_MODULE
from app.core.exceptions import CollegeNotFoundError
from app.core.redis import (
    RedisLockUnavailableError,
    acquire_trigger_lock,
    clear_trigger_idempotency_in_progress,
    get_trigger_idempotency_result,
    release_trigger_lock,
    set_trigger_idempotency_result,
    try_claim_trigger_idempotency,
)
from app.domain.contracts.internal_contracts import (
    CrawlDispatcherPort,
    TriggerCrawlCmd,
    TriggerCrawlResult,
    TriggerCrawlResultKind,
)

logger = logging.getLogger(__name__)


def normalize_trigger_idempotency_key(value: str | None) -> str | None:
    """멱등 키 전처리: strip 후 빈 문자열이면 None. 라우터·서비스 경계에서 공개 사용."""
    if not value:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _resolve_college_codes(college_code: str | None) -> list[str]:
    """college_code 정규화·검증 후 코드 목록. 미등록 단일 코드 시 CollegeNotFoundError."""
    normalized = college_code.strip() if college_code and college_code.strip() else None
    if normalized and normalized not in COLLEGE_CODE_TO_MODULE:
        raise CollegeNotFoundError(normalized)
    return [normalized] if normalized else list(COLLEGE_CODE_TO_MODULE.keys())


@dataclass(frozen=True, slots=True)
class _IdempotencyClaimOutcome:
    """멱등 claim 단계 결과. early_return이 있으면 trigger는 즉시 반환."""

    claimed_for_cleanup: bool
    early_return: TriggerCrawlResult | None


async def _run_idempotency_claim(
    redis: RedisAsyncio | None,
    key_stripped: str | None,
    idempotency_scope: str,
) -> _IdempotencyClaimOutcome:
    if not key_stripped or redis is None:
        return _IdempotencyClaimOutcome(claimed_for_cleanup=True, early_return=None)

    fail_closed = settings.redis.redis_trigger_idempotency_required
    claimed = await try_claim_trigger_idempotency(
        redis,
        key_stripped,
        idempotency_scope,
        fail_closed=fail_closed,
    )
    if claimed:
        return _IdempotencyClaimOutcome(claimed_for_cleanup=True, early_return=None)

    cached = await get_trigger_idempotency_result(redis, key_stripped, idempotency_scope)
    payload = (
        cached
        if cached is not None
        else {
            "detail": "in_progress",
            "code": "IDEMPOTENCY_IN_PROGRESS",
        }
    )
    return _IdempotencyClaimOutcome(
        claimed_for_cleanup=False,
        early_return=TriggerCrawlResult(
            result_kind=TriggerCrawlResultKind.cached,
            payload=payload,
        ),
    )


def _raise_if_lock_required_but_no_redis(redis: RedisAsyncio | None) -> None:
    if redis is None and settings.redis.redis_trigger_lock_required:
        raise RedisLockUnavailableError("Redis trigger lock required but client not configured")


@dataclass(frozen=True, slots=True)
class _EnqueueOutcome:
    result: TriggerCrawlResult
    """False면 멱등 캐시를 저장했으므로 finally에서 claim clear 생략."""

    should_clear_claim_in_finally: bool


async def _enqueue_colleges(
    *,
    redis: RedisAsyncio | None,
    dispatcher: CrawlDispatcherPort,
    codes: list[str],
    claimed: bool,
    key_stripped: str | None,
    idempotency_scope: str,
) -> _EnqueueOutcome:
    stagger = settings.crawl_trigger_stagger_seconds
    task_ids: list[dict] = []
    skipped: list[str] = []
    failed: list[str] = []

    for i, code in enumerate(codes):
        lock_token: str | None = None
        if redis is not None:
            try:
                acquired, lock_token = await acquire_trigger_lock(redis, code)
            except RedisLockUnavailableError:
                logger.exception(
                    "Trigger lock unavailable (Redis error) for college_code=%s",
                    code,
                    extra={"college_code": code},
                )
                failed.append(code)
                continue
            if not acquired:
                skipped.append(code)
                continue

        countdown = i * stagger if len(codes) > 1 else 0
        enqueued_at = time.time()
        try:
            task_id = await dispatcher.enqueue(code, lock_token, countdown, enqueued_at)
            task_ids.append(
                {
                    "college_code": code,
                    "task_id": task_id,
                    "countdown_sec": countdown,
                }
            )
            logger.info(
                "trigger-crawl enqueued: college_code=%s task_id=%s countdown=%s",
                code,
                task_id,
                countdown,
            )
        except (ConnectionError, TimeoutError, OSError):
            logger.exception(
                "trigger-crawl apply_async failed: code=%s",
                code,
                extra={"college_code": code},
            )
            if redis is not None and lock_token:
                await release_trigger_lock(redis, code, lock_token)
            failed.append(code)

    out: dict = {"enqueued": len(task_ids), "tasks": task_ids}
    if skipped:
        out["skipped"] = skipped
    if failed:
        out["failed"] = failed
        out["code"] = "ALL_ENQUEUES_FAILED" if len(task_ids) == 0 else "PARTIAL_ENQUEUE_FAILURE"
        out["detail"] = (
            "All crawl enqueues failed; check broker and worker logs."
            if len(task_ids) == 0
            else "One or more colleges failed to enqueue; retry recommended."
        )

    has_failed = bool(failed)
    if has_failed:
        return _EnqueueOutcome(
            result=TriggerCrawlResult(result_kind=TriggerCrawlResultKind.partial_failure, payload=out),
            should_clear_claim_in_finally=True,
        )

    should_clear_claim = True
    if claimed and redis is not None and key_stripped is not None and len(task_ids) > 0 and out:
        await set_trigger_idempotency_result(redis, key_stripped, idempotency_scope, out)
        should_clear_claim = False

    return _EnqueueOutcome(
        result=TriggerCrawlResult(result_kind=TriggerCrawlResultKind.success, payload=out),
        should_clear_claim_in_finally=should_clear_claim,
    )


class InternalCrawlService:
    """트리거 크롤 오케스트레이션. Redis·디스패처는 생성자 주입(요청 스코프)."""

    def __init__(
        self,
        redis_client: RedisAsyncio | None,
        dispatcher: CrawlDispatcherPort,
    ) -> None:
        self._redis = redis_client
        self._dispatcher = dispatcher

    async def trigger(self, cmd: TriggerCrawlCmd) -> TriggerCrawlResult:
        """
        트리거 크롤 실행. 멱등성 claim → 락 필요 시 Redis 없으면 infra_unavailable →
        루프에서 락 획득 → enqueue. claimed 상태에서 조기 반환/실패 시 finally에서 clear.
        """
        codes = _resolve_college_codes(cmd.college_code)
        idempotency_scope = codes[0] if len(codes) == 1 else "all"
        key_stripped = normalize_trigger_idempotency_key(cmd.idempotency_key)

        claimed = False
        should_clear_claim = False

        try:
            claim_out = await _run_idempotency_claim(self._redis, key_stripped, idempotency_scope)
            claimed = claim_out.claimed_for_cleanup
            if claim_out.early_return is not None:
                return claim_out.early_return

            should_clear_claim = True

            _raise_if_lock_required_but_no_redis(self._redis)

            enqueue_out = await _enqueue_colleges(
                redis=self._redis,
                dispatcher=self._dispatcher,
                codes=codes,
                claimed=claimed,
                key_stripped=key_stripped,
                idempotency_scope=idempotency_scope,
            )
            should_clear_claim = enqueue_out.should_clear_claim_in_finally
            return enqueue_out.result

        finally:
            if should_clear_claim and claimed and self._redis is not None and key_stripped is not None:
                await clear_trigger_idempotency_in_progress(self._redis, key_stripped, idempotency_scope)
