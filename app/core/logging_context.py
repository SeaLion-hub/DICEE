"""
요청별 로그 컨텍스트. contextvars로 request_id, trace_id, endpoint, user_id_hash, event_code를 보관하고
Filter로 레코드에 주입해 전 구간 일관된 구조화 로그를 만든다.
trace_id는 request_id와 동일 값으로 설정해 로그·Sentry 상관용으로 사용.
환경별 로그 구분: development일 때 [DEV] 접두사로 로컬/운영 구분.
"""

import contextvars
import logging

logger = logging.getLogger(__name__)

# 요청 스코프 컨텍스트 (미들웨어/의존성에서 설정, Filter에서 읽음)
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_request_id", default=None)
_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_trace_id", default=None)
_endpoint: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_endpoint", default=None)
_method: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_method", default=None)
_status_code: contextvars.ContextVar[int | None] = contextvars.ContextVar("logging_status_code", default=None)
_duration_ms: contextvars.ContextVar[int | None] = contextvars.ContextVar("logging_duration_ms", default=None)
_user_id_hash: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_user_id_hash", default=None)
_event_code: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_event_code", default=None)
_college_code: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_college_code", default=None)
_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_run_id", default=None)
_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_task_id", default=None)
_phase: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_phase", default=None)
_crawler: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_crawler", default=None)
_structlog_bind_fail_count = 0
_structlog_clear_fail_count = 0


def _log_structlog_context_error(operation: str, error: Exception, count: int) -> None:
    """Fail-open 유지 + 반복 실패 가시화. 최초 1회 warning, 이후 debug."""
    if count == 1:
        logger.warning(
            "structlog context %s failed once; continuing fail-open",
            operation,
            exc_info=True,
        )
        return
    logger.debug(
        "structlog context %s failed again (count=%d): %s",
        operation,
        count,
        error,
    )


def set_request_context(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    endpoint: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    duration_ms: int | None = None,
    user_id_hash: str | None = None,
    event_code: str | None = None,
    college_code: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
    phase: str | None = None,
    crawler: str | None = None,
) -> None:
    """현재 컨텍스트에 로깅용 필드 설정. 미들웨어·의존성에서 호출. trace_id 미지정 시 request_id와 동일하게 설정."""
    to_bind: dict[str, object] = {}
    if request_id is not None:
        _request_id.set(request_id)
        if request_id:
            to_bind["request_id"] = request_id
    if trace_id is not None:
        _trace_id.set(trace_id)
        if trace_id:
            to_bind["trace_id"] = trace_id
    elif request_id is not None:
        _trace_id.set(request_id)
        if request_id:
            to_bind["trace_id"] = request_id
    if endpoint is not None:
        _endpoint.set(endpoint)
        if endpoint:
            to_bind["endpoint"] = endpoint
    if method is not None:
        _method.set(method)
        if method:
            to_bind["method"] = method
    if status_code is not None:
        _status_code.set(status_code)
        to_bind["status_code"] = status_code
    if duration_ms is not None:
        _duration_ms.set(duration_ms)
        to_bind["duration_ms"] = duration_ms
    if user_id_hash is not None:
        _user_id_hash.set(user_id_hash)
        if user_id_hash:
            to_bind["user_id_hash"] = user_id_hash
    if event_code is not None:
        _event_code.set(event_code)
        if event_code:
            to_bind["event_code"] = event_code
    if college_code is not None:
        _college_code.set(college_code)
        if college_code:
            to_bind["college_code"] = college_code
    if run_id is not None:
        _run_id.set(run_id)
        if run_id:
            to_bind["run_id"] = run_id
    if task_id is not None:
        _task_id.set(task_id)
        if task_id:
            to_bind["task_id"] = task_id
    if phase is not None:
        _phase.set(phase)
        if phase:
            to_bind["phase"] = phase
    if crawler is not None:
        _crawler.set(crawler)
        if crawler:
            to_bind["crawler"] = crawler

    if to_bind:
        try:
            import structlog

            structlog.contextvars.bind_contextvars(**to_bind)
        except Exception as e:
            # Fail-open: logging must never break request handling.
            global _structlog_bind_fail_count
            _structlog_bind_fail_count += 1
            _log_structlog_context_error("bind", e, _structlog_bind_fail_count)


def get_request_context() -> dict[str, str | int | None]:
    """현재 컨텍스트 값 조회 (테스트·수동 로그용)."""
    return {
        "request_id": _request_id.get(None),
        "trace_id": _trace_id.get(None),
        "endpoint": _endpoint.get(None),
        "method": _method.get(None),
        "status_code": _status_code.get(None),
        "duration_ms": _duration_ms.get(None),
        "user_id_hash": _user_id_hash.get(None),
        "event_code": _event_code.get(None),
        "college_code": _college_code.get(None),
        "run_id": _run_id.get(None),
        "task_id": _task_id.get(None),
        "phase": _phase.get(None),
        "crawler": _crawler.get(None),
    }


def clear_request_context() -> None:
    """
    현재 컨텍스트를 비운다.

    - FastAPI 요청 종료 후
    - Celery task 종료 후

    컨텍스트 누수 방지용.
    """
    _request_id.set(None)
    _trace_id.set(None)
    _endpoint.set(None)
    _method.set(None)
    _status_code.set(None)
    _duration_ms.set(None)
    _user_id_hash.set(None)
    _event_code.set(None)
    _college_code.set(None)
    _run_id.set(None)
    _task_id.set(None)
    _phase.set(None)
    _crawler.set(None)
    try:
        import structlog

        structlog.contextvars.clear_contextvars()
    except Exception as e:
        global _structlog_clear_fail_count
        _structlog_clear_fail_count += 1
        _log_structlog_context_error("clear", e, _structlog_clear_fail_count)


class LoggingContextFilter(logging.Filter):
    """
    contextvars에 설정된 request_id, trace_id, endpoint, user_id_hash, event_code를
    로그 레코드에 주입. 포매터에서 %(request_id)s, %(trace_id)s 등으로 사용 가능.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id.get(None) or ""
        if not hasattr(record, "trace_id"):
            record.trace_id = _trace_id.get(None) or _request_id.get(None) or ""
        if not hasattr(record, "endpoint"):
            record.endpoint = _endpoint.get(None) or ""
        if not hasattr(record, "method"):
            record.method = _method.get(None) or ""
        if not hasattr(record, "status_code"):
            record.status_code = _status_code.get(None) or 0
        if not hasattr(record, "duration_ms"):
            record.duration_ms = _duration_ms.get(None) or 0
        if not hasattr(record, "user_id_hash"):
            record.user_id_hash = _user_id_hash.get(None) or ""
        if not hasattr(record, "event_code"):
            record.event_code = _event_code.get(None) or ""
        if not hasattr(record, "college_code"):
            record.college_code = _college_code.get(None) or ""
        if not hasattr(record, "run_id"):
            record.run_id = _run_id.get(None) or ""
        if not hasattr(record, "task_id"):
            record.task_id = _task_id.get(None) or ""
        if not hasattr(record, "phase"):
            record.phase = _phase.get(None) or ""
        if not hasattr(record, "crawler"):
            record.crawler = _crawler.get(None) or ""
        return True


class DevelopmentLogFilter(logging.Filter):
    """
    development 환경에서만 로그 메시지 앞에 [DEV] 접두사 추가.
    로컬과 베타/프로덕션 로그를 한눈에 구분하기 위함.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from app.core.config import settings
        except Exception:
            return True
        env = (settings.environment or "").strip().lower()
        if env != "development":
            return True
        try:
            record.msg = "[DEV] " + record.getMessage()
            record.args = ()
        except Exception:
            record.msg = "[DEV] " + str(record.msg)
            record.args = ()
        return True
