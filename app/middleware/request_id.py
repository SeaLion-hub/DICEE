"""X-Request-ID 미들웨어. 요청마다 ID 설정. Sentry·로그 상관용."""

import logging
import re
import time
import uuid
from collections.abc import Callable

from fastapi import Request
from starlette.background import BackgroundTask, BackgroundTasks
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.logging_context import clear_request_context, set_request_context

logger = logging.getLogger(__name__)

# P2: 길이·문자셋 제한. 초과/비허용 문자면 클라이언트 값 무시하고 새 UUID 사용.
_REQUEST_ID_MAX_LEN = 128
_REQUEST_ID_ALLOWED_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def _sanitize_request_id(raw: str | None) -> str:
    """헤더 값이 유효하면 그대로, 아니면 새 UUID 반환. 로그 오염·카디널리티 폭증 방지."""
    if not raw or not raw.strip():
        return str(uuid.uuid4())
    s = raw.strip()
    if len(s) > _REQUEST_ID_MAX_LEN or not _REQUEST_ID_ALLOWED_PATTERN.match(s):
        return str(uuid.uuid4())
    return s


def _attach_on_response_close(response: Response, func: Callable[[], None]) -> None:
    """응답 종료 시 실행할 후처리 함수를 background task에 안전하게 연결."""
    background = response.background
    if background is None:
        response.background = BackgroundTask(func)
        return
    if isinstance(background, BackgroundTasks):
        background.add_task(func)
        return
    tasks = BackgroundTasks()
    tasks.add_task(background)
    tasks.add_task(func)
    response.background = tasks


class RequestIDMiddleware(BaseHTTPMiddleware):
    """요청마다 X-Request-ID 설정. 클라이언트 값은 길이·문자셋 검증 후 재사용, 없으면 UUID 생성."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        t0 = time.perf_counter()
        raw = request.headers.get("X-Request-ID")
        request_id = _sanitize_request_id(raw)
        request.state.request_id = request_id
        endpoint = getattr(request.url, "path", "") or ""
        method = getattr(request, "method", "") or ""
        set_request_context(
            request_id=request_id,
            endpoint=endpoint,
            method=method,
            user_id_hash="",
            event_code="",
        )
        try:
            import sentry_sdk

            sentry_sdk.set_tag("request_id", request_id)
            sentry_sdk.set_tag("trace_id", request_id)
        except Exception:
            logger.debug("Sentry set_tag failed (request_id/trace_id); continuing.", exc_info=True)
        try:
            response = await call_next(request)
        except Exception:
            # Ensure we don't leak context across requests even on error paths.
            clear_request_context()
            raise
        duration_ms = int((time.perf_counter() - t0) * 1000)
        status_code = getattr(response, "status_code", 0) or 0
        set_request_context(status_code=status_code, duration_ms=duration_ms)
        response.headers["X-Request-ID"] = request_id
        try:
            _attach_on_response_close(response, clear_request_context)
        except Exception:
            # Fallback: best-effort immediate clear (may reduce late logs, but avoids leakage).
            clear_request_context()
        return response
