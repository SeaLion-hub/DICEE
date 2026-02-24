"""FastAPI 앱 진입점. app.main:app"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

# 환경 변수 로드 직후 Sentry 초기화. 임포트/라우터 등록 단계 예외도 수집.
def _init_sentry() -> None:
    """SENTRY_DSN이 있으면 Sentry 초기화. environment는 설정에서 로드(스테이징/로컬 구분)."""
    if settings.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            integrations=[
                FastApiIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            traces_sample_rate=0.1,
            environment=settings.environment,
        )


_init_sentry()

import httpx
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pyjwt_key_fetcher import AsyncKeyFetcher

from app.api import health, internal
from app.api.v1 import auth as v1_auth
from app.core.database import get_async_session_maker, get_engine, init_db, verify_db_connection
from app.core.redis import create_blocklist_client, create_trigger_lock_client
from app.core.state import AppState

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 수명 주기: DB, HTTP 클라이언트·Google Key Fetcher(싱글톤), Redis(Blocklist). DB는 lifespan → app.state → Depends(get_db)."""
    init_db()
    await verify_db_connection()
    state = AppState(
        httpx_client=httpx.AsyncClient(),
        google_key_fetcher=AsyncKeyFetcher(
            valid_issuers=["https://accounts.google.com"],
        ),
        redis_blocklist_client=create_blocklist_client(),
        redis_trigger_lock_client=create_trigger_lock_client(),
        engine=get_engine(),
        async_session_maker=get_async_session_maker(),
    )
    app.state = state
    yield
    await state.httpx_client.aclose()
    if state.redis_blocklist_client is not None:
        await state.redis_blocklist_client.aclose()
    if state.redis_trigger_lock_client is not None:
        await state.redis_trigger_lock_client.aclose()
    if state.engine is not None:
        await state.engine.dispose()


app = FastAPI(
    title="DICEE API",
    description="연세대 공지 매칭 백엔드",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(internal.router)
app.include_router(v1_auth.router, prefix="/v1")

class RequestIDMiddleware(BaseHTTPMiddleware):
    """요청마다 X-Request-ID 설정. 클라이언트가 보내면 재사용, 없으면 UUID 생성. Sentry·로그 상관용."""

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


app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(httpx.HTTPError)
async def httpx_error_handler(request: Request, exc: httpx.HTTPError) -> JSONResponse:
    """Auth 외 다른 경로에서 httpx 예외가 누락되었을 때 503 폴백. detail 추상화 + code로 구분."""
    logger.warning("External HTTP error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Service temporarily unavailable",
            "code": "UPSTREAM_UNAVAILABLE",
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """비즈니스 예외(HTTPException) → 그대로 반환. 그 외 → 500 + 로그. detail 추상화 + code. 500 시 X-Request-ID 헤더로 디버깅 상관."""
    if isinstance(exc, asyncio.CancelledError):
        raise exc  # 정상 연결 종료, 500 로그 방지
    if isinstance(exc, HTTPException):
        content = {"detail": exc.detail}
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
