"""Redis 비동기 클라이언트. Blocklist(Access Token 무효화)용. 풀 크기 명시로 동시 처리량 대응."""

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

BLOCKLIST_KEY_PREFIX = "dicee:blocklist:access:"
# 단과대별 크롤 트리거 분산락. TTL 내 중복 enqueue 방지. 워커 완료 시 조기 해제.
TRIGGER_LOCK_KEY_PREFIX = "dicee:trigger_lock:"
TRIGGER_LOCK_TTL_SECONDS = 600


def create_blocklist_client() -> Any:
    """
    Blocklist용 비동기 Redis 클라이언트. max_connections 명시.
    redis_url 없으면 None. lifespan에서 한 번 생성해 app.state에 보관.
    """
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as redis
    except ImportError:
        logger.warning("redis.asyncio not available. Blocklist disabled.")
        return None
    pool = redis.ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_blocklist_max_connections,
        decode_responses=True,
    )
    return redis.Redis(connection_pool=pool)


async def add_access_to_blocklist(
    client: Any, jti: str, ttl_seconds: int
) -> None:
    """Access Token jti를 Blocklist에 추가. TTL로 자동 만료. client는 redis.asyncio.Redis."""
    if client is None or ttl_seconds <= 0:
        return
    key = f"{BLOCKLIST_KEY_PREFIX}{jti}"
    try:
        await client.set(key, "1", ex=ttl_seconds)
    except Exception as e:
        logger.warning("Blocklist add failed (jti=%s): %s", jti, e, exc_info=True)


async def acquire_trigger_lock(client: Any, college_code: str) -> bool:
    """
    college별 크롤 트리거 락 획득. SET NX EX. 성공 시 True, 이미 잠김 시 False.
    client는 redis.asyncio.Redis. None이면 락 없이 True 반환(비활성).
    """
    if client is None:
        return True
    key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
    try:
        return await client.set(key, "1", nx=True, ex=TRIGGER_LOCK_TTL_SECONDS)
    except Exception as e:
        logger.warning("Trigger lock acquire failed (college=%s): %s", college_code, e, exc_info=True)
        return False


def release_trigger_lock_sync(college_code: str) -> None:
    """
    단과대별 크롤 트리거 락 해제. 워커 완료/예외 시 호출하여 TTL 전 해제.
    동기 Redis 사용(Celery 워커 환경).
    """
    from app.core.config import settings
    if not settings.redis_url:
        return
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
        client.delete(key)
        client.close()
    except Exception as e:
        logger.warning("Trigger lock release failed (college=%s): %s", college_code, e, exc_info=True)


async def is_access_blocked(
    client: Any, jti: str, *, fail_closed: bool
) -> bool:
    """
    jti가 Blocklist에 있으면 True(무효).
    Redis 장애 시: fail_closed=True면 True(인증 거부), False면 False(서명만 믿고 통과).
    """
    if client is None:
        return False
    key = f"{BLOCKLIST_KEY_PREFIX}{jti}"
    try:
        exists = await client.exists(key)
        return bool(exists)
    except Exception as e:
        logger.warning("Blocklist check failed (jti=%s): %s", jti, e, exc_info=True)
        return fail_closed
