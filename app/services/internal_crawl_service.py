"""
내부 API 트리거 크롤 서비스. 멱등성·락·enqueue 오케스트레이션.
HTTP/JSONResponse/status_code 의미를 모름. 도메인 결과(TriggerCrawlResult) 또는 도메인 예외만 사용.
"""

import logging
import time

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


def _resolve_college_codes(college_code: str | None) -> list[str]:
    """college_code 정규화·검증 후 코드 목록. 미등록 단일 코드 시 CollegeNotFoundError."""
    normalized = college_code.strip() if college_code and college_code.strip() else None
    if normalized and normalized not in COLLEGE_CODE_TO_MODULE:
        raise CollegeNotFoundError(f"Unknown college_code: {normalized}. Valid: {list(COLLEGE_CODE_TO_MODULE.keys())}")
    return [normalized] if normalized else list(COLLEGE_CODE_TO_MODULE.keys())


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
        key_stripped = cmd.idempotency_key.strip() if cmd.idempotency_key and cmd.idempotency_key.strip() else None

        claimed = False
        should_clear_claim = False

        try:
            if key_stripped and self._redis is not None:
                fail_closed = settings.redis.redis_trigger_idempotency_required
                claimed = await try_claim_trigger_idempotency(
                    self._redis,
                    key_stripped,
                    idempotency_scope,
                    fail_closed=fail_closed,
                )
                if not claimed:
                    cached = await get_trigger_idempotency_result(self._redis, key_stripped, idempotency_scope)
                    payload = (
                        cached
                        if cached is not None
                        else {
                            "detail": "in_progress",
                            "code": "IDEMPOTENCY_IN_PROGRESS",
                        }
                    )
                    return TriggerCrawlResult(
                        result_kind=TriggerCrawlResultKind.cached,
                        payload=payload,
                    )
            else:
                claimed = True

            should_clear_claim = True

            if self._redis is None and settings.redis.redis_trigger_lock_required:
                raise RedisLockUnavailableError("Redis trigger lock required but client not configured")

            stagger = settings.crawl_trigger_stagger_seconds
            task_ids: list[dict] = []
            skipped: list[str] = []
            failed: list[str] = []

            for i, code in enumerate(codes):
                lock_token: str | None = None
                if self._redis is not None:
                    try:
                        acquired, lock_token = await acquire_trigger_lock(self._redis, code)
                    except RedisLockUnavailableError:
                        logger.exception(
                            "Trigger lock unavailable (Redis error) for college_code=%s",
                            code,
                            extra={"college_code": code},
                        )
                        raise
                    if not acquired:
                        skipped.append(code)
                        continue

                countdown = i * stagger if len(codes) > 1 else 0
                enqueued_at = time.time()
                try:
                    task_id = await self._dispatcher.enqueue(code, lock_token, countdown, enqueued_at)
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
                except Exception:
                    logger.exception("trigger-crawl apply_async failed: code=%s", code)
                    if self._redis is not None and lock_token:
                        await release_trigger_lock(self._redis, code, lock_token)
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
            has_failed_or_skipped = has_failed or bool(skipped)
            if has_failed:
                result_kind = TriggerCrawlResultKind.partial_failure
            else:
                result_kind = TriggerCrawlResultKind.success
                if (
                    claimed
                    and self._redis is not None
                    and key_stripped is not None
                    and not has_failed_or_skipped
                    and out
                ):
                    await set_trigger_idempotency_result(self._redis, key_stripped, idempotency_scope, out)
                    should_clear_claim = False

            return TriggerCrawlResult(result_kind=result_kind, payload=out)

        finally:
            if should_clear_claim and claimed and self._redis is not None and key_stripped is not None:
                await clear_trigger_idempotency_in_progress(self._redis, key_stripped, idempotency_scope)
