"""FastAPI 앱 진입점. app.main:app"""

import asyncio
import logging
from contextlib import asynccontextmanager

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
from app.core.database import get_engine, init_db, verify_db_connection
from app.core.redis import create_blocklist_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 수명 주기: DB, HTTP 클라이언트·Google Key Fetcher(싱글톤), Redis(Blocklist)."""
    init_db()
    await verify_db_connection()
    app.state.httpx_client = httpx.AsyncClient()
    app.state.google_key_fetcher = AsyncKeyFetcher(
        valid_issuers=["https://accounts.google.com"],
    )
    app.state.redis_blocklist_client = create_blocklist_client()
    yield
    await app.state.httpx_client.aclose()
    if getattr(app.state, "redis_blocklist_client", None) is not None:
        await app.state.redis_blocklist_client.aclose()
    eng = get_engine()
    if eng is not None:
        await eng.dispose()


app = FastAPI(
    title="DICEE API",
    description="연세대 공지 매칭 백엔드",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(internal.router)
app.include_router(v1_auth.router, prefix="/v1")

allowed_origins = [
    o.strip() for o in settings.allowed_origins.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(httpx.HTTPError)
async def httpx_error_handler(request: Request, exc: httpx.HTTPError) -> JSONResponse:
    """외부 HTTP 클라이언트(구글 OAuth 등) 지연/타임아웃 시 503. 500 전파 방지."""
    logger.warning("External HTTP error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=503,
        content={"detail": "Service temporarily unavailable"},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """비즈니스 예외(HTTPException) → 그대로 반환. 그 외 → 500 + 로그."""
    if isinstance(exc, asyncio.CancelledError):
        raise exc  # 정상 연결 종료, 500 로그 방지
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    logger.exception("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
