"""
Celery 워커가 실행할 작업(Task) 정의.
동기 DB(psycopg2)·crawl_service.run_crawl_job_sync 사용. "Too many connections" 방지.
"""

import logging
import threading
import time
import uuid as uuid_mod
from pathlib import Path

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
from app.core.redis import release_trigger_lock_sync, renew_trigger_lock_sync
from app.core.storage import (
    SPOOL_RETRY_COUNT_KEY,
    spool_list_local,
    spool_read_entry,
    upload_notice_html,
)
from app.repositories.crawl_run_repository import close_stale_running_runs_sync
from app.repositories.notice_repository import (
    get_notice_for_ai_sync,
    update_ai_result_sync,
    update_notice_content_url_sync,
)
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


def _heartbeat_loop(
    college_code: str,
    lock_token: str | None,
    stop_event: threading.Event,
) -> None:
    """주기적으로 락 TTL 갱신. stop_event가 set될 때까지 TRIGGER_LOCK_HEARTBEAT_INTERVAL_SECONDS마다 실행."""
    while not stop_event.wait(TRIGGER_LOCK_HEARTBEAT_INTERVAL_SECONDS):
        if renew_trigger_lock_sync(college_code, lock_token):
            logger.debug("Trigger lock heartbeat renewed: college=%s", college_code)


@app.task(
    bind=True,
    name="app.services.tasks.crawl_college_task",
    autoretry_for=(RequestException, ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def crawl_college_task(
    self,
    college_code: str,
    lock_token: str | None = None,
    enqueued_at: float | None = None,
):
    """Celery 크롤 태스크. 동기 세션·crawl_college_sync. finally 락 해제; heartbeat로 TTL 갱신."""
    task_id = getattr(self.request, "id", None) or ""
    _set_task_context(str(task_id) if task_id else None, college_code)
    lock_hint = (lock_token[:8] + "…") if lock_token else "none"
    logger.info(
        "Task Started: task_id=%s college_code=%s lock_token=%s",
        task_id, college_code, lock_hint,
    )
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
                session, college_code, task_id, on_chunk
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
        # heartbeat 중지 → join → 락 해제 순서 유지(경합 창 최소화). Lua 소유권 검사로 치명적 오작동 없음.
        stop_heartbeat.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=2.0)
        release_trigger_lock_sync(college_code, lock_token)


@app.task(name="app.services.tasks.close_stale_crawl_runs_task")
def close_stale_crawl_runs_task():
    """
    Stale RUNNING 정리: started_at이 crawl_run_stale_seconds보다 오래된 crawl_runs를 FAILED로 닫음.
    Celery Beat에서 주기 호출 권장(예: 15분마다). CRAWL_RUN_STALE_SECONDS로 임계값 설정.
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
)
def process_notice_ai_task(self, notice_id: str):
    """
    AI 처리 태스크. FOR UPDATE SKIP LOCKED + ai_status 선점으로 동시 워커 중복 처리 방지.
    AI_PIPELINE_ENABLED=False면 스킵(pending 유지). True일 때만 Gemini 호출 후 update_ai_result_sync.
    notice_id: UUID 문자열 (Celery 직렬화용).
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
        # 4단계: Gemini 호출 후 ai_extracted_json 생성. ai_pipeline_enabled=True일 때만 여기 도달.
        logger.info("process_notice_ai_task: task_id=%s notice_id=%s", task_id, notice_id)
        update_ai_result_sync(session, notice_uuid, {})


def _move_spool_to_dlq(path: Path, dlq_dir: Path) -> bool:
    """스풀 파일을 DLQ 디렉터리로 이동. 성공 시 True."""
    try:
        dlq_dir.mkdir(parents=True, exist_ok=True)
        dest = dlq_dir / path.name
        path.rename(dest)
        return True
    except OSError:
        logger.exception("drain_content_spool_task: move to DLQ failed path=%s", path)
        return False


@app.task(name="app.services.tasks.drain_content_spool_task")
def drain_content_spool_task():
    """
    스풀에 쌓인 업로드 실패 건을 재업로드 후 DB(notice_contents)에 반영.
    local 백엔드만 지원. 성공 시 파일 삭제, 최대 재시도·파싱 실패·notice 없음 시 DLQ로 이동.
    재업로드 실패 시 기존 파일을 덮어써 retry_count만 갱신(중복 파일 생성 안 함).
    """
    from app.core.storage import _spool_base_path, spool_overwrite_entry

    backend = (getattr(settings, "content_spool_backend", None) or "local").strip().lower()
    if backend != "local":
        logger.warning(
            "drain_content_spool_task: backend=%s not implemented (only local). "
            "Spool drain skipped; set CONTENT_SPOOL_BACKEND=local or use persistent volume.",
            backend,
        )
        return {"drained": 0, "failed": 0, "dlq": 0}
    base = _spool_base_path()
    dlq_dir = base.parent / (base.name + "_dlq")
    max_retries = getattr(settings, "content_spool_max_retries", 5)
    drained = 0
    dlq_count = 0
    failed = 0
    for path in spool_list_local():
        entry = spool_read_entry(path)
        if not entry:
            if _move_spool_to_dlq(path, dlq_dir):
                dlq_count += 1
            failed += 1
            continue
        try:
            cid = uuid_mod.UUID(entry["college_id"])
        except (ValueError, KeyError):
            if _move_spool_to_dlq(path, dlq_dir):
                dlq_count += 1
            failed += 1
            continue
        eid = entry.get("external_id", "")
        ch = entry.get("content_hash")
        html = entry.get("html_content", "")
        retry = int(entry.get(SPOOL_RETRY_COUNT_KEY, 0))
        content_url = None
        try:
            content_url = upload_notice_html(html, college_id=cid, external_id=eid, content_hash=ch)
        except Exception as e:
            logger.warning("drain_content_spool_task: upload failed path=%s retry=%s error=%s", path, retry, e)
            retry += 1
            if retry >= max_retries:
                if _move_spool_to_dlq(path, dlq_dir):
                    dlq_count += 1
                failed += 1
            else:
                spool_overwrite_entry(path, {**entry, SPOOL_RETRY_COUNT_KEY: retry})
            continue
        if not content_url:
            failed += 1
            continue
        with get_sync_session() as session:
            if update_notice_content_url_sync(session, cid, eid, content_url):
                drained += 1
                try:
                    path.unlink()
                except OSError:
                    logger.warning("drain_content_spool_task: unlink after success failed path=%s", path)
            else:
                logger.warning("drain_content_spool_task: notice not found college_id=%s external_id=%s", cid, eid)
                if _move_spool_to_dlq(path, dlq_dir):
                    dlq_count += 1
                failed += 1
    if drained or dlq_count or failed:
        logger.info(
            "drain_content_spool_task: drained=%s dlq=%s failed=%s",
            drained,
            dlq_count,
            failed,
        )
    return {"drained": drained, "failed": failed, "dlq": dlq_count}
