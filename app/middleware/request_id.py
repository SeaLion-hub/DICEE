"""X-Request-ID 미들웨어. 요청마다 ID 설정. Sentry·로그 상관용."""

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    """요청마다 X-Request-ID 설정. 클라이언트가 보내면 재사용, 없으면 UUID 생성."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            import sentry_sdk
            sentry_sdk.set_tag("request_id", request_id)
        except ImportError:
            pass
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
