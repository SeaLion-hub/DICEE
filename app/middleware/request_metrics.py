"""API 골든 시그널 미들웨어.

request_total, request_error_total, request_duration_seconds.
라벨: endpoint_template, status_class, method만.
"""

import re
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.metrics import (
    REQUEST_DURATION_SECONDS,
    REQUEST_ERROR_TOTAL,
    REQUEST_TOTAL,
    increment,
    set_gauge,
)

_UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _endpoint_template(path: str) -> str:
    """path에서 UUID·숫자 ID를 {id}로 치환해 카디널리티 제한."""
    if not path:
        return "/"
    s = _UUID_PATTERN.sub("{id}", path)
    s = re.sub(r"/\d+(\/|$)", r"/{id}\1", s)
    return s or "/"


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """요청 수·에러 수·지연을 골든 시그널로 기록. 라벨은 endpoint_template, status_class, method만 사용."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        start = time.perf_counter()
        path = getattr(request.url, "path", "") or ""
        endpoint_template = _endpoint_template(path)
        method = getattr(request, "method", "") or ""

        response = await call_next(request)
        status_code = getattr(response, "status_code", 500)
        status_class = f"{status_code // 100}xx"
        duration = time.perf_counter() - start

        labels = {
            "endpoint_template": endpoint_template,
            "status_class": status_class,
            "method": method,
        }
        increment(REQUEST_TOTAL, 1, labels=labels)
        if status_code >= 400:
            increment(REQUEST_ERROR_TOTAL, 1, labels=labels)
        set_gauge(REQUEST_DURATION_SECONDS, duration, labels=labels)

        return response
