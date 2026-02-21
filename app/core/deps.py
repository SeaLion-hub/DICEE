"""FastAPI 의존성. HTTP 클라이언트·Google Key Fetcher·Redis Blocklist 등 앱 생명주기 객체 주입."""

from typing import Any

from fastapi import Request

import httpx
from pyjwt_key_fetcher import AsyncKeyFetcher


def get_httpx_client(request: Request) -> httpx.AsyncClient:
    """
    앱 lifespan에서 생성한 싱글톤 AsyncClient 반환.
    매 요청마다 새 클라이언트를 만들지 않아 소켓 고갈(TIME_WAIT) 방지.
    """
    return request.app.state.httpx_client


def get_google_key_fetcher(request: Request) -> AsyncKeyFetcher:
    """앱 lifespan에서 생성한 Google JWKS AsyncKeyFetcher 싱글톤."""
    return request.app.state.google_key_fetcher


def get_redis_blocklist(request: Request) -> Any:
    """앱 lifespan에서 생성한 Blocklist용 Redis 비동기 클라이언트. 미설정 시 None."""
    return getattr(request.app.state, "redis_blocklist_client", None)
