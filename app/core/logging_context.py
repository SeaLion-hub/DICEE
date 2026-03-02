"""
요청별 로그 컨텍스트. contextvars로 request_id, trace_id, endpoint, user_id_hash, event_code를 보관하고
Filter로 레코드에 주입해 전 구간 일관된 구조화 로그를 만든다.
trace_id는 request_id와 동일 값으로 설정해 로그·Sentry 상관용으로 사용.
환경별 로그 구분: development일 때 [DEV] 접두사로 로컬/운영 구분.
"""

import contextvars
import logging

# 요청 스코프 컨텍스트 (미들웨어/의존성에서 설정, Filter에서 읽음)
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_request_id", default=None)
_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_trace_id", default=None)
_endpoint: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_endpoint", default=None)
_user_id_hash: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_user_id_hash", default=None)
_event_code: contextvars.ContextVar[str | None] = contextvars.ContextVar("logging_event_code", default=None)


def set_request_context(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    endpoint: str | None = None,
    user_id_hash: str | None = None,
    event_code: str | None = None,
) -> None:
    """현재 컨텍스트에 로깅용 필드 설정. 미들웨어·의존성에서 호출. trace_id 미지정 시 request_id와 동일하게 설정."""
    if request_id is not None:
        _request_id.set(request_id)
    if trace_id is not None:
        _trace_id.set(trace_id)
    elif request_id is not None:
        _trace_id.set(request_id)
    if endpoint is not None:
        _endpoint.set(endpoint)
    if user_id_hash is not None:
        _user_id_hash.set(user_id_hash)
    if event_code is not None:
        _event_code.set(event_code)


def get_request_context() -> dict[str, str | None]:
    """현재 컨텍스트 값 조회 (테스트·수동 로그용)."""
    return {
        "request_id": _request_id.get(None),
        "trace_id": _trace_id.get(None),
        "endpoint": _endpoint.get(None),
        "user_id_hash": _user_id_hash.get(None),
        "event_code": _event_code.get(None),
    }


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
        if not hasattr(record, "user_id_hash"):
            record.user_id_hash = _user_id_hash.get(None) or ""
        if not hasattr(record, "event_code"):
            record.event_code = _event_code.get(None) or ""
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
