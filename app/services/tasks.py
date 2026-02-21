"""
Celery 워커가 실행할 작업(Task) 정의.
동기 DB(psycopg2)·crawl_service.crawl_college_sync 사용. "Too many connections" 방지.
"""

import logging
from datetime import UTC, datetime

from celery import shared_task
from requests.exceptions import RequestException

from app.core.database_sync import get_sync_session
from app.core.redis import release_trigger_lock_sync
from app.repositories.college_repository import get_by_external_id_sync as get_college_by_external_id_sync
from app.repositories.crawl_run_repository import create_crawl_run_sync, update_crawl_run_sync
from app.repositories.notice_repository import get_notice_for_ai_sync, update_ai_result_sync
from app.services.crawl_service import crawl_college_sync

logger = logging.getLogger(__name__)


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
def crawl_college_task(college_code: str):
    """Celery 크롤 태스크. 동기 세션·crawl_college_sync. 완료/예외 시 college별 분산락 조기 해제."""
    task_id = getattr(crawl_college_task.request, "id", None) or ""
    _set_task_context(str(task_id) if task_id else None, college_code)
    logger.info("Task Started: task_id=%s college_code=%s", task_id, college_code)
    count = 0
    notice_ids: list[int] = []
    try:
        with get_sync_session() as session:
            college = get_college_by_external_id_sync(session, college_code)
            if not college:
                raise ValueError(f"College not found: {college_code}")
            create_crawl_run_sync(session, college.id, task_id)
            session.commit()
            try:
                count, notice_ids = crawl_college_sync(session, college_code)
                update_crawl_run_sync(
                    session,
                    task_id,
                    finished_at=datetime.now(UTC),
                    status="success",
                    notices_upserted=count,
                )
                session.commit()
            except Exception as e:
                update_crawl_run_sync(
                    session,
                    task_id,
                    finished_at=datetime.now(UTC),
                    status="failed",
                    error_message=(str(e))[:2000],
                )
                session.commit()
                raise
        for nid in notice_ids:
            process_notice_ai_task.delay(nid)
        msg = (
            f"Crawling {college_code} completed. Upserted {count} notices, "
            f"enqueued AI for {len(notice_ids)}."
        )
        logger.info(msg)
        return {"upserted": count, "enqueued_ai": len(notice_ids)}
    finally:
        release_trigger_lock_sync(college_code)


@shared_task(
    name="app.services.tasks.process_notice_ai_task",
    bind=True,
    autoretry_for=(RequestException, ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    rate_limit="10/m",
)
def process_notice_ai_task(self, notice_id: int):
    """
    AI 처리 태스크. FOR UPDATE SKIP LOCKED + ai_status 선점으로 동시 워커 중복 처리 방지.
    선점 실패(이미 처리 중/완료) 시 스킵. 4단계에서 Gemini 호출 구현 시 여기서 호출 후 update_ai_result_sync.
    """
    task_id = getattr(self.request, "id", None) or ""
    _set_task_context(str(task_id) if task_id else None)
    with get_sync_session() as session:
        notice = get_notice_for_ai_sync(session, notice_id)
        if not notice:
            logger.debug(
                "process_notice_ai_task: notice_id=%s not available (already processing/done or not found), skipping",
                notice_id,
            )
            return
        # 4단계: Gemini 호출 후 ai_extracted_json 생성. 현재는 스텁으로 done + 빈 결과 저장.
        logger.info("process_notice_ai_task: task_id=%s notice_id=%s (stub)", task_id, notice_id)
        update_ai_result_sync(session, notice_id, {})
