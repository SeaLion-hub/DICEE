"""Health check 엔드포인트."""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_async_session_maker

router = APIRouter(tags=["health"])


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


def _check_redis() -> str:
    """Redis 연결 상태. PING. 'ok' 또는 'error'. redis_url 없으면 'ok'(미사용)."""
    if not settings.redis_url:
        return "ok"
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url)
        client.ping()
        return "ok"
    except Exception:
        return "error"


@router.get("/health")
async def get_health() -> dict[str, str]:
    """헬스 체크. DB(SELECT 1)·Redis(PING) 포함. status: ok | degraded | error."""
    db_status = await _check_db()
    redis_status = _check_redis()
    if db_status == "ok" and redis_status == "ok":
        status = "ok"
    else:
        status = "degraded" if (db_status == "error" or redis_status == "error") else "ok"
    return {
        "status": status,
        "db": db_status,
        "redis": redis_status,
    }
