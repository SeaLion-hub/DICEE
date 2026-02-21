"""Health check 엔드포인트. Redis는 app.state 비동기 클라이언트 재사용(스레드 풀/동기 클라이언트 미사용)."""

import asyncio

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.core.database import get_async_session_maker

router = APIRouter(tags=["health"])

HEALTH_REDIS_PING_TIMEOUT = 2.0


async def _check_db() -> str:
    """DB 연결 상태. SELECT 1 실행. 'ok' 또는 'error'. DB 미초기화 시 'error'."""
    maker = get_async_session_maker()
    if not maker:
        return "error"
    try:
        async with maker() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


async def _check_redis(request: Request) -> str:
    """Redis 연결 상태. app.state 비동기 클라이언트(Blocklist용) 재사용. PING에 짧은 timeout."""
    client = getattr(request.app.state, "redis_blocklist_client", None)
    if client is None:
        return "ok"
    try:
        await asyncio.wait_for(client.ping(), timeout=HEALTH_REDIS_PING_TIMEOUT)
        return "ok"
    except (asyncio.TimeoutError, Exception):
        return "error"


@router.get("/health")
async def get_health(request: Request) -> dict[str, str]:
    """헬스 체크. DB(SELECT 1)·Redis(PING, 기존 비동기 풀 재사용). status: ok | degraded."""
    db_status = await _check_db()
    redis_status = await _check_redis(request)
    if db_status == "ok" and redis_status == "ok":
        status = "ok"
    else:
        status = "degraded" if (db_status == "error" or redis_status == "error") else "ok"
    return {
        "status": status,
        "db": db_status,
        "redis": redis_status,
    }
