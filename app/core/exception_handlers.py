"""전역 예외 핸들러. 공통 인터페이스: (request, exc) -> JSONResponse, 응답 스키마 { "detail", "code" }."""

import asyncio
import logging

import httpx
from fastapi import Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic 검증 오류. 공통 인터페이스: (request, exc) -> JSONResponse."""
    return await request_validation_exception_handler(request, exc)


async def httpx_error_handler(request: Request, exc: httpx.HTTPError) -> JSONResponse:
    """외부 HTTP 오류(타임아웃 등). 503 + code UPSTREAM_UNAVAILABLE."""
    logger.warning("External HTTP error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Service temporarily unavailable",
            "code": "UPSTREAM_UNAVAILABLE",
        },
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """미처리 예외. HTTPException은 그대로 반환, 그 외 500 + code INTERNAL_ERROR."""
    if isinstance(exc, asyncio.CancelledError):
        raise exc
    if isinstance(exc, HTTPException):
        content: dict = {"detail": exc.detail}
        if hasattr(exc, "code") and exc.code:
            content["code"] = exc.code
        return JSONResponse(status_code=exc.status_code, content=content)
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled exception: %s (request_id=%s)",
        exc,
        request_id,
        exc_info=True,
    )
    response = JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "code": "INTERNAL_ERROR"},
    )
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response
