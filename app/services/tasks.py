"""
Celery 앱은 실행·작업(Task) 정의.
동기 DB(psycopg2)·crawl_service.run_crawl_job_sync 사용. "Too many connections" 방지.
"""

import logging
import threading
import time
import uuid as uuid_mod
from pathlib import Path

import requests
from requests.exceptions import RequestException

from app.core.celery_app import app
from app.core.config import settings
from app.core.database_sync import get_sync_session
from app.core.metrics import (
    CRAWL_DURATION_SECONDS,
    CRAWL_FAILURE_TOTAL,
    CRAWL_SUCCESS_TOTAL,
    ENQUEUE_TO_START_LAG_SECONDS,
    increment,
    set_gauge,
)
from app.core.redis import (
    claim_crawl_task_execution,
    release_crawl_task_execution,
    release_trigger_lock_sync,
    renew_trigger_lock_sync,
)
from app.core.storage import (
    SPOOL_LAST_ERROR_TYPE_KEY,
    SPOOL_RETRY_COUNT_KEY,
    apply_error_metadata,
    spool_delete_local,
    spool_delete_s3,
    spool_list_local,
    spool_list_s3,
    spool_move_to_dlq_local,
    spool_move_to_dlq_s3,
    spool_overwrite_entry,
    spool_overwrite_s3,
    spool_read_entry,
    spool_read_s3,
    upload_notice_html,
)
from app.repositories.crawl_run_repository import close_stale_running_runs_sync
from app.repositories.notice_repository import (
    get_notice_for_ai_sync,
    update_ai_result_sync,
    update_notice_content_url_sync,
)
from app.schemas.ai import NoticeAIExtraction, NoticeCategory
from app.services.ai_pipeline import extract_notice_info, project_extraction_to_notice_fields
from app.services.crawl_service import handle_crawl_failure_composite, run_crawl_job_sync

logger = logging.getLogger(__name__)

TRIGGER_LOCK_HEARTBEAT_INTERVAL_SECONDS = 60
NOTICE_HTML_FETCH_TIMEOUT = 30


def _get_notice_html_for_ai(notice) -> str:
    """공지 본문 HTML 반환. content_url이 있으면 HTTP GET, 없으면 title 기반 최소 HTML."""
    url = None
    if getattr(notice, "notice_content", None) and getattr(notice.notice_content, "content_url", None):
        url = (notice.notice_content.content_url or "").strip()
    if url and (url.startswith("http://") or url.startswith("https://")):
        try:
            resp = requests.get(url, timeout=NOTICE_HTML_FETCH_TIMEOUT)
            resp.raise_for_status()
            return resp.text or ""
        except RequestException:
            raise
    title = getattr(notice, "title", None) or ""
    return f"<title>{title}</title>" if title else ""


def _set_task_context(task_id: str | None, college_code: str | None = None):
    """Sentry·로그인 컨텍스트. task_id·college_code로 4차 분류 등 식별. Fail-open: Sentry 예외 시 로그만 하고 계속."""
    try:
        import sentry_sdk

        if task_id:
            sentry_sdk.set_tag("celery.task_id", task_id)
        if college_code:
            sentry_sdk.set_tag("college_code", college_code)
    except Exception:
        logger.debug("Sentry set_tag failed (task context); continuing.", exc_info=True)


def _heartbeat_loop(
    college_code: str,
    lock_token: str | None,
    stop_event: threading.Event,
) -> None:
    """트리거 락 유지로 TTL 연장. stop_event가 set될 때까지 TRIGGER_LOCK_HEARTBEAT_INTERVAL_SECONDS마다 실행."""
    while not stop_event.wait(TRIGGER_LOCK_HEARTBEAT_INTERVAL_SECONDS):
        if renew_trigger_lock_sync(college_code, lock_token):
            logger.debug("Trigger lock heartbeat renewed: college=%s", college_code)


# Retryable: timeout, 5xx, 408, 409, 425, 429, 네트워크 일시 오류. Fatal(그 외 4xx 등)은 autoretry_for에 넣지 않음.
@app.task(
    bind=True,
    name="app.services.tasks.crawl_college_task",
    autoretry_for=(RequestException, ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=6,
)
def crawl_college_task(
    self,
    college_code: str,
    lock_token: str | None = None,
    enqueued_at: float | None = None,
):
    """Celery 워커 진입점. 동기 세션·crawl_college_sync. finally 락 해제; heartbeat로 TTL 연장."""
    task_id = getattr(self.request, "id", None) or ""
    _set_task_context(str(task_id) if task_id else None, college_code)
    lock_hint = (lock_token[:8] + "...") if lock_token else "none"
    logger.info(
        "Task Started: task_id=%s college_code=%s lock_token=%s",
        task_id,
        college_code,
        lock_hint,
    )
    execution_claimed = False
    if task_id:
        execution_claimed = claim_crawl_task_execution(task_id)
        if not execution_claimed:
            logger.info(
                "Duplicate task delivery skipped: task_id=%s college_code=%s",
                task_id,
                college_code,
            )
            return {"skipped": True, "reason": "duplicate_delivery"}
    labels = {"college_code": college_code}
    if enqueued_at is not None:
        lag = time.time() - enqueued_at
        set_gauge(ENQUEUE_TO_START_LAG_SECONDS, lag, labels=labels)
    count = 0
    enqueued_ai = 0
    failed_enqueues = 0
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
            nonlocal enqueued_ai, failed_enqueues
            for nid in ids:
                try:
                    process_notice_ai_task.delay(str(nid))
                    enqueued_ai += 1
                except Exception as e:
                    failed_enqueues += 1
                    logger.warning(
                        "Failed to enqueue AI task for notice_id=%s (task_id=%s college=%s): %s",
                        nid,
                        task_id,
                        college_code,
                        e,
                        exc_info=True,
                    )

        with get_sync_session() as session:
            count, _ = run_crawl_job_sync(
                session,
                college_code,
                task_id,
                on_chunk,
                failure_publisher=lambda ev: handle_crawl_failure_composite(session, ev),
            )
        increment(CRAWL_SUCCESS_TOTAL, 1, labels=labels)
        msg = (
            f"Crawling {college_code} completed. Upserted {count} notices, "
            f"enqueued AI for {enqueued_ai} (failed_enqueues={failed_enqueues})."
        )
        logger.info(msg)
        return {
            "upserted": count,
            "enqueued_ai": enqueued_ai,
            "failed_enqueues": failed_enqueues,
        }
    except Exception:
        increment(CRAWL_FAILURE_TOTAL, 1, labels=labels)
        raise
    finally:
        set_gauge(CRAWL_DURATION_SECONDS, time.monotonic() - started_at, labels=labels)
        # heartbeat 스레드와 join 타임아웃 해제 후 종료(테스트 등 최소화. Lua 원자성 때문에 분산 락은 유지됨).
        stop_heartbeat.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=2.0)
        release_trigger_lock_sync(college_code, lock_token)
        if execution_claimed and task_id:
            release_crawl_task_execution(task_id)


@app.task(name="app.services.tasks.close_stale_crawl_runs_task")
def close_stale_crawl_runs_task():
    """
    Stale RUNNING 정리: started_at이 crawl_run_stale_seconds보다 오래된 crawl_runs를 FAILED로 전환.
    Celery Beat에서 트리거 실행 무효(미사용 15분 등). CRAWL_RUN_STALE_SECONDS로 기준값 설정.
    """
    older_than = settings.crawl_run_stale_seconds
    with get_sync_session() as session:
        count = close_stale_running_runs_sync(session, older_than)
    if count:
        logger.info("close_stale_crawl_runs_task: closed %d stale RUNNING run(s)", count)
    return {"closed": count}


@app.task(
    name="app.services.tasks.process_notice_ai_task",
    bind=True,
    autoretry_for=(RequestException, ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    rate_limit="10/m",
    max_retries=6,
)
def process_notice_ai_task(self, notice_id: str):
    """
    AI 처리 진입점. FOR UPDATE SKIP LOCKED + ai_status 점으로 동시 작업 병렬 처리 방지.
    AI_PIPELINE_ENABLED=False면 스킵(pending 유지). True면 Gemini 호출 후 update_ai_result_sync.
    notice_id: UUID 문자열(Celery 등록 사용).
    """
    from app.core.config import settings

    if not settings.ai_pipeline_enabled:
        logger.debug(
            "process_notice_ai_task: ai_pipeline_enabled=False; skipping notice_id=%s (pending preserved)",
            notice_id,
        )
        return
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
        logger.info("process_notice_ai_task: task_id=%s notice_id=%s", task_id, notice_id)
        if notice.is_manual_edited:
            update_ai_result_sync(
                session,
                notice_uuid,
                notice.ai_extracted_json or {},
            )
        else:
            html_content = _get_notice_html_for_ai(notice)
            extraction = extract_notice_info(html_content)
            projected = project_extraction_to_notice_fields(extraction)
            update_ai_result_sync(
                session,
                notice_uuid,
                projected["ai_extracted_json"],
                dates=projected["dates"],
                eligibility=projected["eligibility"],
                hashtags=projected["hashtags"],
                category=projected["category"],
            )


def _resolve_spool_backend_ops(backend: str):
    if backend == "local":
        return (
            spool_list_local,
            spool_read_entry,
            spool_overwrite_entry,
            spool_delete_local,
            lambda item, entry, reason: spool_move_to_dlq_local(item, entry, reason=reason),
        )
    if backend == "s3":
        return (
            spool_list_s3,
            spool_read_s3,
            spool_overwrite_s3,
            spool_delete_s3,
            lambda item, entry, reason: spool_move_to_dlq_s3(item, entry, reason=reason),
        )
    return None


@app.task(name="app.services.tasks.drain_content_spool_task")
def drain_content_spool_task():
    """Drain failed content uploads from spool and update notice content URLs."""
    backend = (getattr(settings, "content_spool_backend", None) or "local").strip().lower()
    ephemeral = bool(getattr(settings, "content_spool_allow_ephemeral", False))
    logger.info(
        "drain_content_spool_task: start backend=%s allow_ephemeral=%s",
        backend,
        ephemeral,
    )

    ops = _resolve_spool_backend_ops(backend)
    if ops is None:
        logger.warning("drain_content_spool_task: unsupported backend=%s", backend)
        return {"drained": 0, "failed": 0, "dlq": 0}

    list_fn, read_fn, overwrite_fn, delete_fn, move_to_dlq_fn = ops
    max_retries = int(getattr(settings, "content_spool_max_retries", 5) or 5)

    drained = 0
    dlq_count = 0
    failed = 0

    def _move_to_dlq_or_mark(
        item: Path | str,
        entry: dict,
        *,
        reason: str,
    ) -> bool:
        moved = bool(move_to_dlq_fn(item, entry, reason))
        if moved:
            return True

        marked = apply_error_metadata(
            entry,
            error=f"DLQ move failed: {reason}",
            stage="dlq_move",
            retry_count=int(entry.get(SPOOL_RETRY_COUNT_KEY, 0) or 0),
        )
        overwrite_fn(item, marked)
        return False

    for item in list_fn():
        entry = read_fn(item)
        if not entry:
            _move_to_dlq_or_mark(item, {}, reason="invalid_spool_entry")
            failed += 1
            continue

        try:
            cid = uuid_mod.UUID(entry["college_id"])
        except (ValueError, KeyError, TypeError):
            marked = apply_error_metadata(entry, error="invalid college_id", stage="db_update")
            if _move_to_dlq_or_mark(item, marked, reason="invalid_college_id"):
                dlq_count += 1
            failed += 1
            continue

        eid = entry.get("external_id", "")
        ch = entry.get("content_hash")
        html = entry.get("html_content", "")
        retry = int(entry.get(SPOOL_RETRY_COUNT_KEY, 0) or 0)

        try:
            content_url = upload_notice_html(html, college_id=cid, external_id=eid, content_hash=ch)
        except Exception as e:
            retry += 1
            marked = apply_error_metadata(entry, error=e, stage="upload", retry_count=retry)
            logger.warning(
                "drain_content_spool_task: upload failed item=%s retry=%s error_type=%s",
                item,
                retry,
                marked.get(SPOOL_LAST_ERROR_TYPE_KEY),
            )
            if retry >= max_retries:
                if _move_to_dlq_or_mark(item, marked, reason="max_retries_exceeded"):
                    dlq_count += 1
                failed += 1
            else:
                overwrite_fn(item, marked)
            continue

        if not content_url:
            retry += 1
            marked = apply_error_metadata(
                entry,
                error="upload returned empty content_url",
                stage="upload",
                retry_count=retry,
            )
            if retry >= max_retries:
                if _move_to_dlq_or_mark(item, marked, reason="empty_content_url"):
                    dlq_count += 1
                failed += 1
            else:
                overwrite_fn(item, marked)
            continue

        with get_sync_session() as session:
            if update_notice_content_url_sync(session, cid, eid, content_url):
                drained += 1
                try:
                    delete_fn(item)
                except Exception:
                    logger.warning("drain_content_spool_task: delete after success failed item=%s", item)
            else:
                marked = apply_error_metadata(
                    entry,
                    error="notice not found during content URL update",
                    stage="db_update",
                    retry_count=retry,
                )
                logger.warning(
                    "drain_content_spool_task: notice not found college_id=%s external_id=%s",
                    cid,
                    eid,
                )
                if _move_to_dlq_or_mark(item, marked, reason="notice_not_found"):
                    dlq_count += 1
                failed += 1

    if drained or dlq_count or failed:
        logger.info(
            "drain_content_spool_task: drained=%s dlq=%s failed=%s backend=%s allow_ephemeral=%s",
            drained,
            dlq_count,
            failed,
            backend,
            ephemeral,
        )
    return {"drained": drained, "failed": failed, "dlq": dlq_count}
