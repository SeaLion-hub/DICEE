"""앱 생명주기 상태 타입. lifespan에서 설정하고 deps에서 주입해 타입 안정성을 보장."""

from __future__ import annotations

from typing import Literal

import httpx
from pyjwt_key_fetcher import AsyncKeyFetcher
from redis.asyncio import Redis as RedisAsyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

OperationalMode = Literal["NORMAL", "DEGRADED"]


class AppState:
    """
    FastAPI app.state에 할당하는 타입된 상태.
    lifespan에서 인스턴스 생성 후 필드 설정, deps에서 request.app.state를 이 타입으로 사용.
    DB는 lifespan → app.state → Depends(get_db) 흐름으로 주입.
    """

    httpx_client: httpx.AsyncClient
    google_key_fetcher: AsyncKeyFetcher
    redis_blocklist_client: RedisAsyncio | None
    redis_trigger_lock_client: RedisAsyncio | None
    engine: AsyncEngine | None
    async_session_maker: async_sessionmaker[AsyncSession] | None
    operational_mode: OperationalMode
    consecutive_failure_count: int
    consecutive_success_count: int

    def __init__(
        self,
        *,
        httpx_client: httpx.AsyncClient,
        google_key_fetcher: AsyncKeyFetcher,
        redis_blocklist_client: RedisAsyncio | None = None,
        redis_trigger_lock_client: RedisAsyncio | None = None,
        engine: AsyncEngine | None = None,
        async_session_maker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.httpx_client = httpx_client
        self.google_key_fetcher = google_key_fetcher
        self.redis_blocklist_client = redis_blocklist_client
        self.redis_trigger_lock_client = redis_trigger_lock_client
        self.engine = engine
        self.async_session_maker = async_session_maker
        self.operational_mode = "NORMAL"
        self.consecutive_failure_count = 0
        self.consecutive_success_count = 0
