"""5xx 응답 body 정제 미들웨어. 스택/민감정보 원천 차단(이중 방어)."""

import json
import logging
from typing import Any, cast

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# 5xx 응답에서 허용하는 최소 안전 본문. 이 구조가 아니거나 traceback/예외 메시지 의심 시 교체.
_SAFE_500_BODY = {"detail": "Internal server error", "code": "INTERNAL_ERROR"}
_SENSITIVE_MARKERS = ("Traceback", "File ", '.py", line ', "Exception:", "Error:")
_UNSAFE_FORWARD_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-type",
    "content-encoding",
}


def _response_body_to_str(body: object) -> str:
    """JSONResponse.body 등 Starlette 혼합 타입을 순수 str로 정규화 (타입 체커·in 연산자용)."""
    if isinstance(body, str):
        return body
    if isinstance(body, bytes | bytearray):
        return body.decode("utf-8", errors="replace")
    return bytes(cast(Any, body)).decode("utf-8", errors="replace")


def _filtered_error_headers(headers: dict[str, str]) -> dict[str, str]:
    """5xx 치환 응답으로 전달하면 안 되는 헤더를 제거한다."""
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in _UNSAFE_FORWARD_HEADERS:
            continue
        out[k] = v
    return out


class Sanitize5xxMiddleware(BaseHTTPMiddleware):
    """
    5xx 응답 body에 스택/예외 메시지가 포함되었을 수 있으면 안전한 JSON으로 교체.
    global_exception_handler가 이미 안전 응답만 반환하더라도, 이중 방어로 원천 차단.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
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
            text = _response_body_to_str(body)
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
                headers=_filtered_error_headers(dict(response.headers)),
            )
        except Exception as e:
            logger.warning("Sanitize5xxMiddleware: %s", e, exc_info=True)
        return response
