"""Crawl failure recording and run_crawl_job_sync entrypoint."""

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import CrawlRunStatus
from app.core.redis import get_shared_sync_redis_client
from app.domain.contracts.crawl_contracts import CrawlJobFailed
from app.repositories.college_repository import get_by_external_id_sync as get_college_by_external_id_sync
from app.repositories.crawl_run_repository import (
    create_or_update_crawl_run_sync,
    ensure_crawl_run_task_sync,
    update_crawl_run_sync,
)

from .pipeline_sync import crawl_college_sync

logger = logging.getLogger(__name__)


CRAWL_FAILURE_REDIS_KEY_PREFIX = "dicee:crawl_failure:"
CRAWL_FAILURE_REDIS_TTL_SECONDS = 86400 * 7


def _record_crawl_failure_fallback(
    run_id: uuid.UUID,
    task_id: str,
    college_code: str,
    error_message: str,
    *,
    reason_code: str = "unknown",
) -> None:
    """
    DB 장애 시 실패 컨텍스트를 Redis에 기록해 중앙에서 추적 가능하게 함.
    Redis 미설정/장애 시 로그만 남기고 반환(예외 전파하지 않음).
    """
    raw_url = (settings.redis.redis_url or "").strip()
    if not raw_url:
        logger.warning(
            "Crawl failure fallback skipped: REDIS_URL not set (run_id=%s task_id=%s college_code=%s)",
            run_id,
            task_id,
            college_code,
        )
        return
    try:
        client = get_shared_sync_redis_client()
        if client is None:
            raise RuntimeError("shared redis client unavailable")
        key = f"{CRAWL_FAILURE_REDIS_KEY_PREFIX}{run_id}"
        payload = {
            "run_id": str(run_id),
            "task_id": task_id,
            "college_code": college_code,
            "error_message": error_message[:2000],
            "reason_code": reason_code,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        client.set(key, json.dumps(payload), ex=CRAWL_FAILURE_REDIS_TTL_SECONDS)
        logger.info(
            "Crawl failure context recorded to Redis (run_id=%s key=%s)",
            run_id,
            key,
        )
    except Exception as redis_err:
        logger.warning(
            "Failed to record crawl failure to Redis (run_id=%s): %s",
            run_id,
            redis_err,
            exc_info=True,
        )


def handle_crawl_failure_composite(session: Session, event: CrawlJobFailed) -> None:
    """
    단일 컴포지트 핸들러: DB FAILED 기록 → 실패 시 Redis fallback.
    """
    try:
        update_crawl_run_sync(
            session,
            event.run_id,
            finished_at=datetime.now(UTC),
            status=CrawlRunStatus.FAILED.value,
            error_message=event.error_message,
        )
        session.commit()
    except Exception as record_err:
        logger.warning(
            "Failed to record crawl run FAILED in DB (run_id=%s): %s",
            event.run_id,
            record_err,
            exc_info=True,
        )
        _record_crawl_failure_fallback(
            event.run_id,
            event.task_id,
            event.college_code,
            event.error_message,
            reason_code=event.reason_code,
        )


def _noop_failure_publisher(_event: CrawlJobFailed) -> None:
    """테스트용 no-op 발행자."""
    pass


def run_crawl_job_sync(
    session: Session,
    college_code: str,
    task_id: str,
    on_chunk_processed: Callable[[list[uuid.UUID]], None],
    *,
    failure_publisher: Callable[[CrawlJobFailed], None] | None = None,
) -> tuple[int, int]:
    """
    크롤 작업 한 건 실행 (college 조회 + crawl_run 생성/갱신 + crawl_college_sync).
    반환: (upserted 개수, enqueued_ai 개수).
    enqueued_ai는 on_chunk_processed가 성공적으로 호출된 notice id 수 기준.
    """
    from app.core.logging_context import clear_request_context, get_request_context, set_request_context

    # Celery worker is long-lived: always reset context at task start.
    clear_request_context()
    set_request_context(event_code="", college_code=college_code, task_id=task_id, phase="job")

    college = get_college_by_external_id_sync(session, college_code)
    if not college:
        raise ValueError(f"College not found: {college_code}")
    run_id = ensure_crawl_run_task_sync(session, task_id)
    create_or_update_crawl_run_sync(session, run_id, college.id)
    session.commit()
    set_request_context(run_id=str(run_id))
    enqueued_ai_count = 0

    def _counting_chunk_handler(ids: list[uuid.UUID]) -> None:
        nonlocal enqueued_ai_count
        if not ids:
            return
        on_chunk_processed(ids)
        enqueued_ai_count += len(ids)

    try:
        count, _ = crawl_college_sync(
            session,
            college_code,
            run_id=run_id,
            task_id=task_id,
            on_chunk_processed=_counting_chunk_handler,
        )
        update_crawl_run_sync(
            session,
            run_id,
            finished_at=datetime.now(UTC),
            status=CrawlRunStatus.SUCCESS.value,
            notices_upserted=count,
        )
        session.commit()
        return (count, enqueued_ai_count)
    except Exception as e:
        session.rollback()
        error_msg = (str(e))[:2000]
        reason_raw = get_request_context().get("event_code")
        reason = reason_raw.strip() if isinstance(reason_raw, str) else "unknown"
        reason = reason or "unknown"
        event = CrawlJobFailed(
            run_id=run_id,
            task_id=task_id,
            college_code=college_code,
            error_message=error_msg,
            reason_code=reason,
        )
        publisher = failure_publisher if failure_publisher is not None else _noop_failure_publisher
        publisher(event)
        raise
    finally:
        clear_request_context()
