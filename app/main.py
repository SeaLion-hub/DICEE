"""FastAPI 앱 진입점. app.main:app"""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from pyjwt_key_fetcher import AsyncKeyFetcher

from app.api import health, internal
from app.api.v1 import auth as v1_auth
from app.core.config import settings
from app.core.database import (
    check_pool_budget,
    get_async_session_maker,
    get_engine,
    get_resolved_max_connections,
    init_db,
    verify_db_connection,
)
from app.core.redis import create_blocklist_client, create_trigger_lock_client
from app.core.state import AppState
from app.core.exception_handlers import (
    validation_exception_handler,
    httpx_error_handler,
    global_exception_handler,
)
from app.middleware import RequestIDMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 수명 주기: Sentry 정식 초기화, DB, HTTP·Key Fetcher, Redis. DB는 lifespan → app.state → Depends(get_db)."""
    # Sentry: lifespan 진입 시점에만 초기화. 임포트 단계 예외는 run.py 부트스트랩에서 수집.
    if settings.sentry_dsn:
        try:
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
        except Exception as e:
            logger.warning("Sentry init skipped: %s", e)

    init_db()
    await verify_db_connection()
    effective_max_conn = (
        settings.db_max_connections
        if settings.db_max_connections is not None
        else get_resolved_max_connections()
    )
    budget_result = check_pool_budget(effective_max_conn)
    if not budget_result.within_budget and budget_result.app_budget > 0:
        if settings.db_pool_strict_budget:
            raise RuntimeError(budget_result.message)
        logger.critical("%s", budget_result.message)
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("context", "db_capacity")
                scope.set_context(
                    "pool_budget",
                    {
                        "peak_pool_conn": budget_result.peak_pool_conn,
                        "app_budget": budget_result.app_budget,
                        "total_pool_conn": budget_result.total_pool_conn,
                    },
                )
                sentry_sdk.capture_message(budget_result.message, level="error")
        except ImportError:
            pass
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

    # 종료 시점: 각 리소스를 개별적으로 정리해, 하나의 실패가 나머지 해제를 막지 않도록 한다.
    try:
        await state.httpx_client.aclose()
    except Exception as e:
        logger.warning("httpx_client close failed during shutdown: %s", e, exc_info=True)

    try:
        if state.redis_blocklist_client is not None:
            await state.redis_blocklist_client.aclose()
    except Exception as e:
        logger.warning(
            "redis_blocklist_client close failed during shutdown: %s", e, exc_info=True
        )

    try:
        if state.redis_trigger_lock_client is not None:
            await state.redis_trigger_lock_client.aclose()
    except Exception as e:
        logger.warning(
            "redis_trigger_lock_client close failed during shutdown: %s", e, exc_info=True
        )

    try:
        if state.engine is not None:
            await state.engine.dispose()
    except Exception as e:
        logger.warning("DB engine dispose failed during shutdown: %s", e, exc_info=True)


app = FastAPI(
    title="DICEE API",
    description="연세대 공지 매칭 백엔드",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(internal.router)
app.include_router(v1_auth.router, prefix="/v1")

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
app.add_exception_handler(httpx.HTTPError, httpx_error_handler)
app.add_exception_handler(Exception, global_exception_handler)
