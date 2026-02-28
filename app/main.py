"""FastAPI 앱 진입점. app.main:app"""

import logging
from contextlib import asynccontextmanager
from typing import cast

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import State

from app.api import health, internal
from app.api.v1 import auth as v1_auth
from app.core.config import settings

if settings.app_entry != "api":
    raise RuntimeError(
        "API process must run with APP_ENTRY=api. "
        f"Current APP_ENTRY={settings.app_entry!r}. Set APP_ENTRY=api for uvicorn/gunicorn."
    )

from app.core.exception_handlers import (
    global_exception_handler,
    httpx_error_handler,
    invalid_forwarded_header_handler,
    validation_exception_handler,
)
from app.core.lifespan import (
    check_startup_crawler_contract,
    check_startup_pool_budget,
    create_app_state,
    init_database,
    init_sentry,
    teardown_state,
)
from app.core.network import InvalidForwardedHeaderError
from app.middleware import RequestIDMiddleware, Sanitize5xxMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 수명 주기: init_sentry → init_database → check_startup_pool_budget → create_app_state → yield → teardown."""
    init_sentry()
    # 프로덕션: 예외 traceback 로그 누출 원천 차단(프레임워크 레벨)
    if (settings.environment or "").strip().lower() == "production":
        from app.core.logging_safety import ProductionExceptionFilter
        logging.getLogger().addFilter(ProductionExceptionFilter())
    await init_database()
    check_startup_pool_budget()
    check_startup_crawler_contract()
    state = create_app_state()
    app.state = cast(State, state)
    yield
    await teardown_state(state)


app = FastAPI(
    title="DICEE API",
    description="연세대 공지 매칭 백엔드",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(internal.router)
app.include_router(v1_auth.router, prefix="/v1")

app.add_middleware(Sanitize5xxMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        "X-Crawl-Trigger-Secret",
        "Idempotency-Key",
    ],
)

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(InvalidForwardedHeaderError, invalid_forwarded_header_handler)
app.add_exception_handler(httpx.HTTPError, httpx_error_handler)
app.add_exception_handler(Exception, global_exception_handler)
