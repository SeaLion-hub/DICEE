"""
Celery 워커가 실행할 작업(Task) 정의.
동기 DB(psycopg2)·crawl_service.run_crawl_job_sync 사용. "Too many connections" 방지.
"""

import logging
import threading
import time

from celery import shared_task
from requests.exceptions import RequestException

from app.core.database_sync import get_sync_session
from app.core.metrics import CRAWL_DURATION_SECONDS, set_gauge
from app.core.redis import release_trigger_lock_sync, renew_trigger_lock_sync
from app.repositories.notice_repository import get_notice_for_ai_sync, update_ai_result_sync
from app.services.crawl_service import run_crawl_job_sync

logger = logging.getLogger(__name__)

TRIGGER_LOCK_HEARTBEAT_INTERVAL_SECONDS = 60


def _set_task_context(task_id: str | None, college_code: str | None = None):
    """Sentry·로그용 컨텍스트. task_id·college_code로 4단계 디버깅 용이."""
    try:
        import sentry_sdk

        if task_id:
            sentry_sdk.set_tag("celery.task_id", task_id)
        if college_code:
            sentry_sdk.set_tag("college_code", college_code)
    except ImportError:
        pass


@shared_task(
    name="app.services.tasks.crawl_college_task",
    autoretry_for=(RequestException, ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def _heartbeat_loop(
    college_code: str,
    lock_token: str | None,
    stop_event: threading.Event,
) -> None:
    """주기적으로 락 TTL 갱신. stop_event가 set될 때까지 TRIGGER_LOCK_HEARTBEAT_INTERVAL_SECONDS마다 실행."""
    while not stop_event.wait(TRIGGER_LOCK_HEARTBEAT_INTERVAL_SECONDS):
        if renew_trigger_lock_sync(college_code, lock_token):
            logger.debug("Trigger lock heartbeat renewed: college=%s", college_code)


def crawl_college_task(college_code: str, lock_token: str | None = None):
    """Celery 크롤 태스크. 동기 세션·crawl_college_sync. 성공 시에만 락 해제; 장시간 실행 중 heartbeat로 TTL 갱신."""
    task_id = getattr(crawl_college_task.request, "id", None) or ""
    _set_task_context(str(task_id) if task_id else None, college_code)
    lock_hint = (lock_token[:8] + "…") if lock_token else "none"
    logger.info(
        "Task Started: task_id=%s college_code=%s lock_token=%s",
        task_id, college_code, lock_hint,
    )
    count = 0
    enqueued_ai = 0
    started_at = time.monotonic()
    stop_heartbeat = threading.Event()
    heartbeat_thread: threading.Thread | None = None
    if lock_token:
        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(college_code, lock_token, stop_heartbeat),
            daemon=True,
        )
        heartbeat_thread.start()
    try:
        def on_chunk(ids: list) -> None:
            for nid in ids:
                process_notice_ai_task.delay(str(nid))

        with get_sync_session() as session:
            count, enqueued_ai = run_crawl_job_sync(
                session, college_code, task_id, on_chunk
            )
        set_gauge(CRAWL_DURATION_SECONDS, time.monotonic() - started_at)
        msg = (
            f"Crawling {college_code} completed. Upserted {count} notices, "
            f"enqueued AI for {enqueued_ai}."
        )
        logger.info(msg)
        release_trigger_lock_sync(college_code, lock_token)
        return {"upserted": count, "enqueued_ai": enqueued_ai}
    finally:
        stop_heartbeat.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=2.0)


@shared_task(
    name="app.services.tasks.process_notice_ai_task",
    bind=True,
    autoretry_for=(RequestException, ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    rate_limit="10/m",
)
def process_notice_ai_task(self, notice_id: str):
    """
    AI 처리 태스크. FOR UPDATE SKIP LOCKED + ai_status 선점으로 동시 워커 중복 처리 방지.
    선점 실패(이미 처리 중/완료) 시 스킵. 4단계에서 Gemini 호출 구현 시 여기서 호출 후 update_ai_result_sync.
    notice_id: UUID 문자열 (Celery 직렬화용).
    """
    import uuid as uuid_mod
    notice_uuid = uuid_mod.UUID(notice_id)
    task_id = getattr(self.request, "id", None) or ""
    _set_task_context(str(task_id) if task_id else None)
    with get_sync_session() as session:
        notice = get_notice_for_ai_sync(session, notice_uuid)
        if not notice:
            logger.debug(
                "process_notice_ai_task: notice_id=%s not available (already processing/done or not found), skipping",
                notice_id,
            )
            return
        # 4단계: Gemini 호출 후 ai_extracted_json 생성. 현재는 스텁으로 done + 빈 결과 저장.
        logger.info("process_notice_ai_task: task_id=%s notice_id=%s (stub)", task_id, notice_id)
        update_ai_result_sync(session, notice_uuid, {})
