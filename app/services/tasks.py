"""
Celery 앱은 실행·작업(Task) 정의.
동기 DB(psycopg)·crawl_service.run_crawl_job_sync 사용. "Too many connections" 방지.
"""

import logging
import threading
import time
import uuid as uuid_mod
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast

import requests
from requests.exceptions import RequestException
from sqlalchemy.orm import Session

from app.core.celery_app import app
from app.core.config import settings
from app.core.database_sync import get_sync_session
from app.core.metrics import (
    AI_ENQUEUE_FAILED_TOTAL,
    CRAWL_DURATION_SECONDS,
    CRAWL_FAILURE_TOTAL,
    CRAWL_SUCCESS_TOTAL,
    ENQUEUE_TO_START_LAG_SECONDS,
    NOTICE_AI_EXTRACTION_COMPLETED_TOTAL,
    increment,
    set_gauge,
)
from app.core.redis import (
    claim_crawl_task_execution,
    push_ai_extraction_completed_stub_sync,
    record_last_crawl_success_sync,
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
from app.core.url_safety import is_safe_worker_http_url
from app.domain.contracts.ai_extraction import NoticeAIExtraction
from app.repositories.crawl_run_repository import close_stale_running_runs_sync
from app.repositories.notice_repository import (
    get_notice_for_ai_sync,
    update_ai_result_sync,
    update_notice_content_url_sync,
)
from app.services.ai_pipeline import extract_notice_info, project_extraction_to_notice_fields
from app.services.crawl_service import handle_crawl_failure_composite, run_crawl_job_sync

logger = logging.getLogger(__name__)


def _coerce_dataclass_or_dict_to_plain_dict(obj: object) -> dict[str, Any]:
    if is_dataclass(obj) and not isinstance(obj, type):
        return cast(dict[str, Any], asdict(obj))
    if isinstance(obj, dict):
        return cast(dict[str, Any], obj)
    msg = f"Expected dataclass instance or dict, got {type(obj).__name__}"
    raise TypeError(msg)

TRIGGER_LOCK_HEARTBEAT_INTERVAL_SECONDS = 60
NOTICE_HTML_FETCH_TIMEOUT = 30

# crawl_college_task → AI 큐 적재 브로커 일시 장애 시 짧은 백오프 재시도
_AI_ENQUEUE_MAX_ATTEMPTS = 4
_AI_ENQUEUE_BASE_DELAY_SEC = 0.25
_AI_ENQUEUE_MAX_DELAY_SEC = 4.0



def _get_notice_html_for_ai(notice) -> str:
    """공지 본문 HTML 반환. content_url이 있으면 HTTP GET, 없으면 title 기반 최소 HTML."""
    url = None
    if getattr(notice, "notice_content", None) and getattr(notice.notice_content, "content_url", None):
        url = (notice.notice_content.content_url or "").strip()
    if url and (url.startswith("http://") or url.startswith("https://")):
        if not is_safe_worker_http_url(url):
            logger.warning(
                "Skipping notice HTML fetch: URL blocked by worker safety policy (notice content_url)",
            )
        else:
            try:
                resp = requests.get(url, timeout=NOTICE_HTML_FETCH_TIMEOUT)
                resp.raise_for_status()
                return resp.text or ""
            except RequestException:
                raise
    title = getattr(notice, "title", None) or ""
    return f"<title>{title}</title>" if title else ""


MAX_IMAGES_FOR_AI = 5


def _get_notice_image_urls_for_ai(notice, max_count: int = MAX_IMAGES_FOR_AI) -> list[str]:
    """공지 이미지 URL 목록 반환. AI 추출 시 Image.from_url 입력용. 최대 max_count개."""
    images = getattr(notice, "images", None)
    if not images or not isinstance(images, list):
        return []
    urls: list[str] = []
    for item in images[:max_count]:
        if not isinstance(item, dict):
            continue
        u = (item.get("url") or item.get("src") or "").strip()
        if u and (u.startswith("http://") or u.startswith("https://")) and is_safe_worker_http_url(u):
            urls.append(u)
    return urls


def _emit_notice_ai_extraction_completed(notice_id_str: str, notice: object) -> None:
    """DB에 AI 결과 반영 후 호출. 메트릭·로그·Redis 스텁 큐(실패 fail-open)."""
    college = getattr(notice, "college", None)
    ext = getattr(college, "external_id", None) if college is not None else None
    code = (str(ext).strip() if ext is not None else "") or "unknown"
    increment(NOTICE_AI_EXTRACTION_COMPLETED_TOTAL, 1, labels={"college_code": code})
    logger.info(
        "notice_ai_extraction_completed",
        extra={"notice_id": notice_id_str, "college_code": code},
    )
    push_ai_extraction_completed_stub_sync(notice_id_str, code)


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


def _delay_process_notice_ai_with_backoff(notice_id: str) -> None:
    """process_notice_ai_task.delay() 호출. 일시 실패 시 지수 백오프로 재시도."""
    last_exc: Exception | None = None
    delay_sec = _AI_ENQUEUE_BASE_DELAY_SEC
    for attempt in range(_AI_ENQUEUE_MAX_ATTEMPTS):
        try:
            process_notice_ai_task.delay(notice_id)
            return
        except Exception as e:
            last_exc = e
            if attempt == _AI_ENQUEUE_MAX_ATTEMPTS - 1:
                break
            time.sleep(min(delay_sec, _AI_ENQUEUE_MAX_DELAY_SEC))
            delay_sec = min(delay_sec * 2.0, _AI_ENQUEUE_MAX_DELAY_SEC)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("AI enqueue retry exhausted without exception")


def _delay_process_notice_ai_batch_with_backoff(notice_ids: list[str]) -> None:
    """process_notice_ai_batch_task.delay() 호출. 일시 실패 시 지수 백오프로 재시도."""
    if not notice_ids:
        return
    last_exc: Exception | None = None
    delay_sec = _AI_ENQUEUE_BASE_DELAY_SEC
    for attempt in range(_AI_ENQUEUE_MAX_ATTEMPTS):
        try:
            process_notice_ai_batch_task.delay(notice_ids)
            return
        except Exception as e:
            last_exc = e
            if attempt == _AI_ENQUEUE_MAX_ATTEMPTS - 1:
                break
            time.sleep(min(delay_sec, _AI_ENQUEUE_MAX_DELAY_SEC))
            delay_sec = min(delay_sec * 2.0, _AI_ENQUEUE_MAX_DELAY_SEC)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("AI batch enqueue retry exhausted without exception")


def _execute_notice_ai_pipeline(
    session: Session,
    notice_uuid: uuid_mod.UUID,
    notice_id_str: str,
    task_id: str,
) -> bool:
    """
    단일 공지 AI 처리(세션 내). Gemini를 호출한 경우 True, 그 외(스킵·수동·폴백) False.
    배치 태스크가 호출 간 스로틀에 사용한다.
    """
    notice = get_notice_for_ai_sync(session, notice_uuid)
    if not notice:
        logger.debug(
            "process_notice_ai_task: notice_id=%s not available (already processing/done or not found), skipping",
            notice_id_str,
        )
        return False
    logger.info("process_notice_ai_task: task_id=%s notice_id=%s", task_id, notice_id_str)
    if notice.is_manual_edited:
        update_ai_result_sync(
            session,
            notice_uuid,
            notice.ai_extracted_json or {},
        )
        _emit_notice_ai_extraction_completed(notice_id_str, notice)
        return False
    html_content = _get_notice_html_for_ai(notice)
    image_urls = _get_notice_image_urls_for_ai(notice)
    college_name = getattr(getattr(notice, "college", None), "name", None)
    if not college_name or not str(college_name).strip():
        logger.warning(
            "process_notice_ai_task: missing college.name; storing fallback extraction notice_id=%s",
            notice_id_str,
        )
        fallback = NoticeAIExtraction(target_departments=[])
        envelope_meta = {
            "provider": "none",
            "model": "none",
            "fallback_reason": "missing_college_name",
        }
        projected = project_extraction_to_notice_fields(
            fallback,
            envelope_meta=envelope_meta,
        )
        update_ai_result_sync(
            session,
            notice_uuid,
            projected["ai_extracted_json"],
            dates=projected["dates"],
            eligibility=projected["eligibility"],
            hashtags=projected["hashtags"],
            taxonomy_rows=projected.get("taxonomy_rows"),
        )
        _emit_notice_ai_extraction_completed(notice_id_str, notice)
        return False
    envelope = extract_notice_info(
        html_content,
        image_urls=image_urls,
        title=notice.title,
        college_name=str(college_name),
    )
    merged_envelope_meta: dict[str, Any] = {
        **_coerce_dataclass_or_dict_to_plain_dict(envelope.meta),
        "usage": _coerce_dataclass_or_dict_to_plain_dict(envelope.usage),
    }
    projected = project_extraction_to_notice_fields(
        envelope.result,
        envelope_meta=merged_envelope_meta,
    )
    update_ai_result_sync(
        session,
        notice_uuid,
        projected["ai_extracted_json"],
        dates=projected["dates"],
        eligibility=projected["eligibility"],
        hashtags=projected["hashtags"],
        taxonomy_rows=projected.get("taxonomy_rows"),
    )
    _emit_notice_ai_extraction_completed(notice_id_str, notice)
    return True


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
            if not ids:
                return
            str_ids = [str(nid) for nid in ids]
            n = len(str_ids)
            try:
                _delay_process_notice_ai_batch_with_backoff(str_ids)
                enqueued_ai += n
            except Exception as e:
                failed_enqueues += n
                increment(AI_ENQUEUE_FAILED_TOTAL, n, labels={"college_code": college_code})
                logger.warning(
                    "Failed to enqueue AI batch (task_id=%s college=%s count=%s): %s",
                    task_id,
                    college_code,
                    n,
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
        record_last_crawl_success_sync(college_code)
        increment(CRAWL_SUCCESS_TOTAL, 1, labels=labels)
        logger.info(
            "crawl_college_completed",
            extra={
                "task_id": task_id,
                "college_code": college_code,
                "upserted": count,
                "enqueued_ai": enqueued_ai,
                "failed_enqueues": failed_enqueues,
            },
        )
        logger.info(
            "Crawling %s completed. Upserted %s notices, enqueued AI for %s (failed_enqueues=%s).",
            college_code,
            count,
            enqueued_ai,
            failed_enqueues,
        )
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
    try:
        notice_uuid = uuid_mod.UUID(notice_id)
    except ValueError:
        logger.warning(
            "process_notice_ai_task: invalid notice_id (not a UUID), ignoring task_id=%s raw=%r",
            getattr(self.request, "id", None) or "",
            notice_id,
        )
        return
    task_id = getattr(self.request, "id", None) or ""
    _set_task_context(str(task_id) if task_id else None)
    with get_sync_session() as session:
        _execute_notice_ai_pipeline(session, notice_uuid, notice_id, task_id)


@app.task(
    name="app.services.tasks.process_notice_ai_batch_task",
    bind=True,
    autoretry_for=(RequestException, ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    rate_limit="10/m",
    max_retries=6,
    soft_time_limit=7200,
    time_limit=7320,
)
def process_notice_ai_batch_task(self, notice_ids: list[str]) -> None:
    """
    크롤 upsert 청크당 1회 브로커 적재. ID 순서대로 처리하며 Gemini 호출이 있었던 항목 뒤에 스로틀 sleep.
    """
    from app.core.config import settings

    if not settings.ai_pipeline_enabled:
        logger.debug(
            "process_notice_ai_batch_task: ai_pipeline_enabled=False; skipping batch len=%s (pending preserved)",
            len(notice_ids or []),
        )
        return
    if not notice_ids:
        return
    task_id = getattr(self.request, "id", None) or ""
    _set_task_context(str(task_id) if task_id else None)
    spacing = float(settings.ai_batch_gemini_spacing_seconds or 0.0)
    prev_gemini = False
    for nid_str in notice_ids:
        if prev_gemini and spacing > 0:
            time.sleep(spacing)
        try:
            notice_uuid = uuid_mod.UUID(nid_str)
        except ValueError:
            logger.warning(
                "process_notice_ai_batch_task: invalid notice_id (not a UUID), ignoring task_id=%s raw=%r",
                task_id,
                nid_str,
            )
            prev_gemini = False
            continue
        with get_sync_session() as session:
            prev_gemini = _execute_notice_ai_pipeline(session, notice_uuid, nid_str, task_id)


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
