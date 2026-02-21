"""FastAPI 앱 진입점. app.main:app"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import health, internal
from app.api.v1 import auth as v1_auth
from app.core.config import settings
from app.core.database import engine, init_db, verify_db_connection

logger = logging.getLogger(__name__)


def _init_sentry() -> None:
    """SENTRY_DSN이 있으면 Sentry 초기화."""
    if settings.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[
                FastApiIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            traces_sample_rate=0.1,
            environment="production",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 수명 주기: Sentry 초기화, DB 연결 검증."""
    _init_sentry()
    init_db()
    await verify_db_connection()
    yield
    if engine is not None:
        await engine.dispose()


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
