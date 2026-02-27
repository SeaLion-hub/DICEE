"""5xx 응답 body 정제 미들웨어. 스택/민감정보 원천 차단(이중 방어)."""

import json
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 5xx 응답에서 허용하는 최소 안전 본문. 이 구조가 아니거나 traceback/예외 메시지 의심 시 교체.
_SAFE_500_BODY = {"detail": "Internal server error", "code": "INTERNAL_ERROR"}
_SENSITIVE_MARKERS = ("Traceback", "File ", ".py\", line ", "Exception:", "Error:")


class Sanitize5xxMiddleware(BaseHTTPMiddleware):
    """
    5xx 응답 body에 스택/예외 메시지가 포함되었을 수 있으면 안전한 JSON으로 교체.
    global_exception_handler가 이미 안전 응답만 반환하더라도, 이중 방어로 원천 차단.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if response.status_code < 500:
            return response
        # StreamingResponse 등은 body 수정 불가; JSONResponse만 처리
        if not hasattr(response, "body"):
            return response
        try:
            body = response.body
            if not body:
                return response
            text = body.decode("utf-8", errors="replace")
            # 이미 안전한 JSON(detail + code만)이면 유지
            try:
                data = json.loads(text)
                if isinstance(data, dict) and "detail" in data and "code" in data:
                    if not any(m in text for m in _SENSITIVE_MARKERS):
                        return response
            except (json.JSONDecodeError, TypeError):
                pass
            # 민감 마커 포함 또는 비표준 구조면 안전 본문으로 교체
            return JSONResponse(
                status_code=response.status_code,
                content=_SAFE_500_BODY,
                headers=dict(response.headers),
            )
        except Exception as e:
            logger.warning("Sanitize5xxMiddleware: %s", e, exc_info=True)
        return response
