"""
앱 수명 주기: Sentry, DB, AppState 초기화 및 병렬 해제(Concurrent Teardown).
shutdown 시 asyncio.gather(..., return_exceptions=True)로 한 리소스 타임아웃이 전체를 블로킹하지 않도록 함.
"""

import asyncio
import logging

import httpx
from pyjwt_key_fetcher import AsyncKeyFetcher

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

logger = logging.getLogger(__name__)

TEARDOWN_TIMEOUT_SECONDS = 10


def init_sentry() -> None:
    """Sentry 초기화. lifespan 진입 시점에만 수행."""
    if not settings.sentry_dsn:
        return
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
        logger.warning("Sentry init skipped: %s", e, exc_info=True)


async def init_database() -> None:
    """DB 초기화: init_db + verify_db_connection."""
    init_db()
    await verify_db_connection()


def check_startup_pool_budget() -> None:
    """부팅 시 풀 예산 검사. 초과 시 strict면 RuntimeError, 아니면 critical 로그 + Sentry."""
    effective_max_conn = (
        settings.db.db_max_connections
        if settings.db.db_max_connections is not None
        else get_resolved_max_connections()
    )
    budget_result = check_pool_budget(effective_max_conn)
    if not budget_result.within_budget and budget_result.app_budget > 0:
        if settings.db.db_pool_strict_budget:
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


def create_app_state() -> AppState:
    """AppState 인스턴스 생성 (httpx, KeyFetcher, Redis, engine, session_maker)."""
    return AppState(
        httpx_client=httpx.AsyncClient(),
        google_key_fetcher=AsyncKeyFetcher(
            valid_issuers=["https://accounts.google.com"],
        ),
        redis_blocklist_client=create_blocklist_client(),
        redis_trigger_lock_client=create_trigger_lock_client(),
        engine=get_engine(),
        async_session_maker=get_async_session_maker(),
    )


async def teardown_state(state: AppState) -> None:
    """
    리소스 병렬 해제. asyncio.gather(..., return_exceptions=True)로 한 타임아웃이 전체를 막지 않도록 함.
    """
    async def close_httpx() -> None:
        await state.httpx_client.aclose()

    async def close_redis_blocklist() -> None:
        if state.redis_blocklist_client is not None:
            await state.redis_blocklist_client.aclose()

    async def close_redis_trigger_lock() -> None:
        if state.redis_trigger_lock_client is not None:
            await state.redis_trigger_lock_client.aclose()

    async def dispose_engine() -> None:
        if state.engine is not None:
            await state.engine.dispose()

    tasks = [
        asyncio.wait_for(close_httpx(), TEARDOWN_TIMEOUT_SECONDS),
        asyncio.wait_for(close_redis_blocklist(), TEARDOWN_TIMEOUT_SECONDS),
        asyncio.wait_for(close_redis_trigger_lock(), TEARDOWN_TIMEOUT_SECONDS),
        asyncio.wait_for(dispose_engine(), TEARDOWN_TIMEOUT_SECONDS),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError):
            logger.warning("teardown collected exception: %s", r, exc_info=not isinstance(r, asyncio.TimeoutError))
