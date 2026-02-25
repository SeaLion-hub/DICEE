"""Health check 엔드포인트. Redis는 app.state 비동기 클라이언트 재사용(스레드 풀/동기 클라이언트 미사용)."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings

router = APIRouter(tags=["health"])

HEALTH_REDIS_PING_TIMEOUT = 2.0


async def _check_db(request: Request) -> str:
    """DB 연결 상태. SELECT 1 실행. app.state.async_session_maker 단일 경로만 사용."""
    maker = getattr(request.app.state, "async_session_maker", None)
    if not maker:
        return "error"
    try:
        async with maker() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


async def _ping_redis(client: object | None) -> str:
    """단일 Redis 클라이언트 PING. None이면 ok(미설정)."""
    if client is None:
        return "ok"
    try:
        await asyncio.wait_for(client.ping(), timeout=HEALTH_REDIS_PING_TIMEOUT)
        return "ok"
    except (asyncio.TimeoutError, Exception):
        return "error"


async def _check_redis_blocklist(request: Request) -> str:
    """Blocklist용 Redis 연결 상태."""
    client = getattr(request.app.state, "redis_blocklist_client", None)
    return await _ping_redis(client)


async def _check_redis_trigger_lock(request: Request) -> str:
    """Trigger 락용 Redis 연결 상태. 부분 장애 노출. Redis 필수인데 None이면 error."""
    client = getattr(request.app.state, "redis_trigger_lock_client", None)
    if client is None and getattr(settings, "redis_trigger_lock_required", False):
        return "error"
    return await _ping_redis(client)


@router.get("/live")
async def get_live() -> dict[str, str]:
    """Liveness: 프로세스 생존만. DB/Redis 미체크. Kubernetes 등 재시작 유도용."""
    return {"status": "ok"}


@router.get("/ready")
async def get_ready(request: Request) -> JSONResponse:
    """Readiness: DB 및 Redis(blocklist·trigger_lock) 준비 시 200. 실패 시 503."""
    db_status = await _check_db(request)
    redis_blocklist = await _check_redis_blocklist(request)
    redis_trigger_lock = await _check_redis_trigger_lock(request)
    ok = (
        db_status == "ok"
        and redis_blocklist == "ok"
        and redis_trigger_lock == "ok"
    )
    content = {
        "status": "ok" if ok else "not_ready",
        "db": db_status,
        "redis_blocklist": redis_blocklist,
        "redis_trigger_lock": redis_trigger_lock,
    }
    return JSONResponse(status_code=200 if ok else 503, content=content)


@router.get("/health")
async def get_health(request: Request) -> dict[str, str]:
    """
    헬스 체크(공개용). DB·Redis 세부 상태는 숨기고 요약 status만 노출.
    status: ok | degraded.
    """
    db_status = await _check_db(request)
    redis_blocklist = await _check_redis_blocklist(request)
    redis_trigger_lock = await _check_redis_trigger_lock(request)
    any_error = (
        db_status == "error"
        or redis_blocklist == "error"
        or redis_trigger_lock == "error"
    )
    status = "ok" if not any_error else "degraded"
    return {"status": status}
