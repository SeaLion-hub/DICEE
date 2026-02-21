"""
Celery 워커가 실행할 작업(Task) 정의.
동기 DB(psycopg2)·crawl_service.crawl_college_sync 사용. "Too many connections" 방지.
"""

import logging
from datetime import UTC, datetime

from celery import shared_task
from requests.exceptions import RequestException

from app.core.database_sync import get_sync_session
from app.repositories.college_repository import get_by_external_id_sync as get_college_by_external_id_sync
from app.repositories.crawl_run_repository import create_crawl_run_sync, update_crawl_run_sync
from app.repositories.notice_repository import get_by_id_sync as get_notice_by_id_sync
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
    """Celery가 호출하는 크롤 태스크. 동기 세션·crawl_college_sync 사용. content_hash 변경 분만 AI 큐 enqueue."""
    task_id = getattr(crawl_college_task.request, "id", None) or ""
    _set_task_context(str(task_id) if task_id else None, college_code)
    logger.info("Task Started: task_id=%s college_code=%s", task_id, college_code)
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
    4단계 AI 처리용 스텁. notice_id로 DB에서 raw_html 등 조회 후 Gemini 호출은 4단계에서 구현.
    이미 ai_extracted_json이 있으면 스킵(멱등). 현재는 로그만. rate_limit은 4단계 Gemini RPM 대비.
    """
    task_id = getattr(self.request, "id", None) or ""
    _set_task_context(str(task_id) if task_id else None)
    with get_sync_session() as session:
        notice = get_notice_by_id_sync(session, notice_id)
        if not notice:
            logger.warning("process_notice_ai_task: notice_id=%s not found, skipping", notice_id)
            return
        if notice.ai_extracted_json:
            logger.debug(
                "process_notice_ai_task: notice_id=%s already processed (ai_extracted_json), skipping",
                notice_id,
            )
            return
    logger.info("process_notice_ai_task: task_id=%s notice_id=%s (stub, 4단계에서 구현)", task_id, notice_id)
