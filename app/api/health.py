"""Health check 엔드포인트. Redis는 app.state 비동기 클라이언트 재사용(스레드 풀/동기 클라이언트 미사용)."""

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings

router = APIRouter(tags=["health"])

HEALTH_REDIS_PING_TIMEOUT = 2.0

logger = logging.getLogger(__name__)


async def _check_db(request: Request) -> str:
    """DB 연결 상태. SELECT 1 실행. app.state.async_session_maker 단일 경로만 사용."""
    maker = getattr(request.app.state, "async_session_maker", None)
    if not maker:
        return "error"
    try:
        async with maker() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception as e:
        logger.warning("Health DB check failed: %s", e, exc_info=True)
        return "error"


async def _ping_redis(client: object | None) -> str:
    """단일 Redis 클라이언트 PING. None이면 ok(미설정)."""
    if client is None:
        return "ok"
    try:
        await asyncio.wait_for(client.ping(), timeout=HEALTH_REDIS_PING_TIMEOUT)
        return "ok"
    except TimeoutError as e:
        logger.warning("Health Redis ping timeout: %s", e, exc_info=True)
        return "error"
    except Exception as e:
        logger.warning("Health Redis ping failed: %s", e, exc_info=True)
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
    """Readiness: DB 및 Redis(blocklist·trigger_lock) 준비 시 200. 실패 시 503.
    Fail-Open(redis_blocklist_fail_closed=False)인 경우 blocklist Redis 장애·예외만으로는 503이 아님.
    blocklist 체크 예외 시 fail_closed=False면 blocklist_ok=True로 판정."""
    db_status = await _check_db(request)
    try:
        redis_blocklist = await _check_redis_blocklist(request)
    except Exception as e:
        logger.warning("Readiness blocklist check exception: %s", e, exc_info=True)
        redis_blocklist = "error"
    blocklist_ok = (redis_blocklist == "ok") or not settings.redis_blocklist_fail_closed
    redis_trigger_lock = await _check_redis_trigger_lock(request)
    ok = (
        db_status == "ok"
        and blocklist_ok
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
async def get_health() -> dict[str, str]:
    """
    플랫폼 헬스체크용(로드밸런서·오토스케일러). 프로세스 기동 여부만 확인.
    DB/Redis 미체크 → Redis·DB 장애 시에도 인스턴스가 비정상 판정되지 않아 장애 전파를 줄인다.
    종속성 준비 상태는 /ready, 상세 진단은 /ready (503 시 body) 사용.
    """
    return {"status": "ok"}
