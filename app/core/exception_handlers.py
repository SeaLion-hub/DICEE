"""전역 예외 핸들러. 공통 인터페이스: (request, exc) -> JSONResponse, 응답 스키마 { "detail", "code" }."""

import asyncio
import logging
from typing import cast

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    CollegeNotFoundError,
)
from app.core.redis import (
    RedisIdempotencyUnavailableError,
    RedisLockUnavailableError,
)

logger = logging.getLogger(__name__)

INTERNAL_CRAWL_503_DETAIL = "Service temporarily unavailable. Try again later."


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Pydantic 검증 오류. Starlette 시그니처 (Request, Exception) 준수."""
    return await request_validation_exception_handler(request, cast(RequestValidationError, exc))


async def invalid_forwarded_header_handler(request: Request, exc: Exception) -> JSONResponse:
    """X-Forwarded-For 규격 이탈. 400 Bad Request, 요청 Drop (fallback 금지)."""
    logger.warning("Invalid X-Forwarded-For: %s (request_id=%s)", exc, getattr(request.state, "request_id", None))
    return JSONResponse(
        status_code=400,
        content={"detail": "Invalid X-Forwarded-For header", "code": "INVALID_FORWARDED_HEADER"},
    )


async def httpx_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """외부 HTTP 오류(타임아웃 등). 503 + code UPSTREAM_UNAVAILABLE."""
    logger.warning("External HTTP error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Service temporarily unavailable",
            "code": "UPSTREAM_UNAVAILABLE",
        },
    )


async def college_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    """미등록 college_code. 400 Bad Request."""
    return JSONResponse(
        status_code=400,
        content={"detail": str(cast(CollegeNotFoundError, exc)), "code": "COLLEGE_NOT_FOUND"},
    )


async def internal_crawl_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """내부 크롤 API 인프라/비즈니스 오류. 503 Service Unavailable."""
    if isinstance(exc, RedisLockUnavailableError):
        code = "REDIS_LOCK_UNAVAILABLE"
    elif isinstance(exc, RedisIdempotencyUnavailableError):
        code = "REDIS_IDEMPOTENCY_UNAVAILABLE"
    else:
        code = "INTERNAL_CRAWL_UNAVAILABLE"
    request_id = getattr(request.state, "request_id", None)
    logger.warning(
        "Internal crawl error: code=%s exc_type=%s",
        code,
        type(exc).__name__,
        extra={"code": code, "request_id": request_id},
    )
    return JSONResponse(
        status_code=503,
        content={"detail": INTERNAL_CRAWL_503_DETAIL, "code": code},
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """미처리 예외. HTTPException은 그대로 반환, 그 외 500 + code INTERNAL_ERROR."""
    if isinstance(exc, asyncio.CancelledError):
        raise exc
    if isinstance(exc, HTTPException):
        content: dict = {"detail": exc.detail}
        if hasattr(exc, "code") and exc.code:
            content["code"] = exc.code
        headers = getattr(exc, "headers", None) or {}
        return JSONResponse(status_code=exc.status_code, content=content, headers=dict(headers))
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
