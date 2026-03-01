"""X-Request-ID 미들웨어. 요청마다 ID 설정. Sentry·로그 상관용."""

import re
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging_context import set_request_context

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


class RequestIDMiddleware(BaseHTTPMiddleware):
    """요청마다 X-Request-ID 설정. 클라이언트 값은 길이·문자셋 검증 후 재사용, 없으면 UUID 생성."""

    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get("X-Request-ID")
        request_id = _sanitize_request_id(raw)
        request.state.request_id = request_id
        endpoint = getattr(request.url, "path", "") or ""
        set_request_context(request_id=request_id, endpoint=endpoint)
        try:
            import sentry_sdk

            sentry_sdk.set_tag("request_id", request_id)
        except ImportError:
            pass
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
