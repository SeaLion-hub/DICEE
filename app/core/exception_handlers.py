"""전역 예외 핸들러. (request, exc) -> JSONResponse. 응답 스키마: detail, code, errors?, request_id?."""

import asyncio
import json
import logging
from typing import Any, cast

from fastapi import Request
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


def _normalize_detail(detail: Any) -> str:
    """HTTPException.detail을 응답 body용 문자열로 통일. 클라이언트는 항상 문자열 detail을 받음."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict | list):
        try:
            return json.dumps(detail, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(detail)
    return str(detail) if detail is not None else ""


def _error_content(
    detail: str,
    code: str,
    request_id: str | None = None,
    errors: list[Any] | None = None,
) -> dict[str, Any]:
    """공통 에러 응답 body. 모든 핸들러가 동일 필드 집합 사용."""
    out: dict[str, Any] = {"detail": detail, "code": code}
    if request_id is not None and request_id:
        out["request_id"] = request_id
    if errors is not None:
        out["errors"] = errors
    return out


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Pydantic 검증 오류. 공통 포맷: detail, code VALIDATION_ERROR, errors, request_id."""
    request_id = getattr(request.state, "request_id", None)
    exc_c = cast(RequestValidationError, exc)
    content = _error_content(
        detail="Validation error",
        code="VALIDATION_ERROR",
        request_id=request_id,
        errors=list(exc_c.errors()),
    )
    return JSONResponse(status_code=422, content=content)


async def invalid_forwarded_header_handler(request: Request, exc: Exception) -> JSONResponse:
    """X-Forwarded-For 규격 이탈. 400 Bad Request, 요청 Drop (fallback 금지)."""
    request_id = getattr(request.state, "request_id", None)
    logger.warning("Invalid X-Forwarded-For: %s (request_id=%s)", exc, request_id)
    return JSONResponse(
        status_code=400,
        content=_error_content(
            detail="Invalid X-Forwarded-For header",
            code="INVALID_FORWARDED_HEADER",
            request_id=request_id,
        ),
    )


async def httpx_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """외부 HTTP 오류(타임아웃 등). 503 + code UPSTREAM_UNAVAILABLE."""
    request_id = getattr(request.state, "request_id", None)
    logger.warning("External HTTP error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=503,
        content=_error_content(
            detail="Service temporarily unavailable",
            code="UPSTREAM_UNAVAILABLE",
            request_id=request_id,
        ),
    )


async def college_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    """미등록 college_code. 400 Bad Request."""
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=400,
        content=_error_content(
            detail=str(cast(CollegeNotFoundError, exc)),
            code="COLLEGE_NOT_FOUND",
            request_id=request_id,
        ),
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
        content=_error_content(
            detail=INTERNAL_CRAWL_503_DETAIL,
            code=code,
            request_id=request_id,
        ),
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """미처리 예외. HTTPException은 detail 정규화 후 code/request_id 포함해 반환, 그 외 500 + INTERNAL_ERROR."""
    if isinstance(exc, asyncio.CancelledError):
        raise exc
    request_id = getattr(request.state, "request_id", None)
    if isinstance(exc, HTTPException):
        detail_str = _normalize_detail(exc.detail)
        code = getattr(exc, "code", None) if hasattr(exc, "code") else None
        if not code:
            code = "HTTP_ERROR"
        content = _error_content(detail=detail_str, code=code, request_id=request_id)
        headers = getattr(exc, "headers", None) or {}
        return JSONResponse(status_code=exc.status_code, content=content, headers=dict(headers))
    logger.exception(
        "Unhandled exception: %s (request_id=%s)",
        exc,
        request_id,
        exc_info=True,
    )
    content = _error_content(
        detail="Internal server error",
        code="INTERNAL_ERROR",
        request_id=request_id,
    )
    response = JSONResponse(status_code=500, content=content)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response
