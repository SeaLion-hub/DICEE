"""FastAPI 의존성. HTTP 클라이언트·Google Key Fetcher·Redis Blocklist 등 앱 생명주기 객체 주입."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

import httpx

if TYPE_CHECKING:
    from app.services.crawl_stats_service import CrawlStatsService
    from app.services.internal_crawl_service import InternalCrawlService
from fastapi import Depends, Request
from pyjwt_key_fetcher import AsyncKeyFetcher
from redis.asyncio import Redis as RedisAsyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import ReadOnlySessionWrapper, get_db, get_read_only_db
from app.core.state import AppState

# 표준 DB 세션 DI alias. 라우터에서는 이 타입만 사용해 get_db/get_read_only_db 의존성을 주입받는다.
SessionDep = Annotated[AsyncSession, Depends(get_db)]
ReadOnlySessionDep = Annotated[ReadOnlySessionWrapper, Depends(get_read_only_db)]


def get_httpx_client(request: Request) -> httpx.AsyncClient:
    """
    앱 lifespan에서 생성한 싱글톤 AsyncClient 반환.
    매 요청마다 새 클라이언트를 만들지 않아 소켓 고갈(TIME_WAIT) 방지.
    """
    return cast(AppState, request.app.state).httpx_client


def get_google_key_fetcher(request: Request) -> AsyncKeyFetcher:
    """앱 lifespan에서 생성한 Google JWKS AsyncKeyFetcher 싱글톤."""
    return cast(AppState, request.app.state).google_key_fetcher


def get_redis_blocklist(request: Request) -> RedisAsyncio | None:
    """앱 lifespan에서 생성한 Blocklist용 Redis 비동기 클라이언트. 미설정 시 None."""
    return cast(AppState, request.app.state).redis_blocklist_client


def get_redis_trigger_lock(request: Request) -> RedisAsyncio | None:
    """앱 lifespan에서 생성한 Trigger 락 전용 Redis 비동기 클라이언트. 미설정 시 None."""
    return cast(AppState, request.app.state).redis_trigger_lock_client


def get_internal_crawl_service(
    redis_client: RedisAsyncio | None = Depends(get_redis_trigger_lock),
) -> InternalCrawlService:
    """요청 스코프 InternalCrawlService. Redis는 Depends(get_redis_trigger_lock)로 주입해 테스트 override 적용."""
    from app.adapters.celery_crawl_dispatcher import CeleryCrawlDispatcher
    from app.services.internal_crawl_service import InternalCrawlService

    return InternalCrawlService(redis_client=redis_client, dispatcher=CeleryCrawlDispatcher())


def get_crawl_stats_service() -> CrawlStatsService:
    """요청 스코프 CrawlStatsService. CrawlStatsQueryPort는 내부에서 어댑터로 주입."""
    from app.repositories.crawl_run_repository import CrawlRunRepositoryAdapter
    from app.services.crawl_stats_service import CrawlStatsService

    return CrawlStatsService(query_port=CrawlRunRepositoryAdapter())
