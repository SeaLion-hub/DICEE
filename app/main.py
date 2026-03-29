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
from app.api.v1 import calendar as v1_calendar
from app.api.v1 import meta as v1_meta
from app.api.v1 import notices as v1_notices
from app.api.v1 import notices_matched as v1_notices_matched
from app.api.v1 import users as v1_users
from app.core.config import settings

if settings.app_entry != "api":
    raise RuntimeError(
        "API process must run with APP_ENTRY=api. "
        f"Current APP_ENTRY={settings.app_entry!r}. Set APP_ENTRY=api for uvicorn/gunicorn."
    )

from app.core.exception_handlers import (
    college_not_found_handler,
    global_exception_handler,
    httpx_error_handler,
    internal_crawl_error_handler,
    invalid_forwarded_header_handler,
    validation_exception_handler,
)
from app.core.exceptions import CollegeNotFoundError, InternalCrawlError
from app.core.lifespan import (
    check_startup_crawler_contract,
    check_startup_pool_budget,
    create_app_state,
    init_database,
    init_sentry,
    preload_crawl_runtime_config,
    teardown_state,
)
from app.core.network import InvalidForwardedHeaderError, warn_trusted_proxy_configuration
from app.middleware import RequestIDMiddleware, RequestMetricsMiddleware, Sanitize5xxMiddleware

logger = logging.getLogger(__name__)

_env = (settings.environment or "").strip().lower()
# 프로덕션: 스키마·엔드포인트 노출 축소 (OpenAPI/Swagger/ReDoc 비활성)
_OPENAPI_DISABLED = _env == "production"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 수명 주기: init_sentry → init_database → check_startup_pool_budget → create_app_state → yield → teardown."""
    init_sentry()
    warn_trusted_proxy_configuration()
    # Structured logging (safe rollout via LOG_FORMAT=json|pretty)
    from app.core.logging import configure_logging

    # 요청별 로그 컨텍스트(request_id, endpoint 등) 주입
    from app.core.logging_context import DevelopmentLogFilter, LoggingContextFilter

    current_env = (settings.environment or "").strip().lower()
    configure_logging(environment=current_env)
    logging.getLogger().addFilter(LoggingContextFilter())
    # development일 때 [DEV] 접두사로 로컬/운영 로그 구분
    if current_env == "development":
        logging.getLogger().addFilter(DevelopmentLogFilter())
    # 프로덕션: 예외 traceback 로그 누출 원천 차단(프레임워크 레벨)
    if current_env == "production":
        from app.core.logging_safety import ProductionExceptionFilter

        logging.getLogger().addFilter(ProductionExceptionFilter())
    await init_database()
    check_startup_pool_budget()
    check_startup_crawler_contract()
    preload_crawl_runtime_config()
    state = create_app_state()
    app.state = cast(State, state)
    yield
    await teardown_state(state)


app = FastAPI(
    title="DICEE API",
    description="연세대 공지 매칭 백엔드",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _OPENAPI_DISABLED else "/docs",
    redoc_url=None if _OPENAPI_DISABLED else "/redoc",
    openapi_url=None if _OPENAPI_DISABLED else "/openapi.json",
)

app.include_router(health.router)
app.include_router(internal.router)
app.include_router(v1_auth.router, prefix="/v1")
app.include_router(v1_meta.router, prefix="/v1")
app.include_router(v1_users.router, prefix="/v1")
app.include_router(v1_calendar.feed_router, prefix="/v1")
app.include_router(v1_calendar.user_cal_router, prefix="/v1")
app.include_router(v1_notices_matched.router, prefix="/v1")
app.include_router(v1_notices.router, prefix="/v1")

app.add_middleware(Sanitize5xxMiddleware)
app.add_middleware(RequestMetricsMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
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
app.add_exception_handler(CollegeNotFoundError, college_not_found_handler)
app.add_exception_handler(InternalCrawlError, internal_crawl_error_handler)
app.add_exception_handler(Exception, global_exception_handler)
