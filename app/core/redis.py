"""Redis 비동기 클라이언트. Blocklist(Access Token 무효화)용. 풀 크기 명시로 동시 처리량 대응."""

import logging
import uuid
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

BLOCKLIST_KEY_PREFIX = "dicee:blocklist:access:"
# 단과대별 크롤 트리거 분산락. TTL 내 중복 enqueue 방지. 워커 완료 시 조기 해제.
# 좀비 락 복구: 워커 하드 킬/파티션 시 TTL 만료로만 해제. Compare-and-del은 정상 종료 시 타인 락 삭제 방지용.
TRIGGER_LOCK_KEY_PREFIX = "dicee:trigger_lock:"
TRIGGER_LOCK_TTL_SECONDS = 600

# Lua: 값이 token일 때만 삭제 (소유권 검증). 1=삭제됨, 0=소유자 아님/키 없음.
LUA_RELEASE_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class RedisLockUnavailableError(Exception):
    """Redis 인프라 오류로 락 획득/해제 불가. Router에서 503 + code REDIS_LOCK_UNAVAILABLE으로 변환."""

    pass


def _redis_pool_kwargs() -> dict:
    """Redis ConnectionPool 공통 옵션. 타임아웃·디코드."""
    return {
        "decode_responses": True,
        "socket_timeout": getattr(settings, "redis_socket_timeout", 5.0),
        "socket_connect_timeout": getattr(settings, "redis_socket_connect_timeout", 2.0),
    }


def create_blocklist_client() -> Any:
    """
    Blocklist용 비동기 Redis 클라이언트. max_connections·타임아웃 명시.
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
        **_redis_pool_kwargs(),
    )
    return redis.Redis(connection_pool=pool)


def create_trigger_lock_client() -> Any:
    """
    Trigger 락 전용 비동기 Redis 클라이언트. Blocklist 풀과 분리해 인증 장애 전파 완화.
    단일 Redis 인스턴스는 SPOF이므로 풀 분리만으로는 완전 격리 아님(CAUTIONS 참고).
    """
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as redis
    except ImportError:
        logger.warning("redis.asyncio not available. Trigger lock disabled.")
        return None
    pool = redis.ConnectionPool.from_url(
        settings.redis_url,
        max_connections=getattr(settings, "redis_trigger_lock_max_connections", 5),
        **_redis_pool_kwargs(),
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


async def acquire_trigger_lock(client: Any, college_code: str) -> tuple[bool, str | None]:
    """
    college별 크롤 트리거 락 획득. SET key <uuid> NX EX.
    성공 시 (True, token), 이미 잠김 시 (False, None).
    Redis 인프라 오류 시 RedisLockUnavailableError 발생.
    client는 redis.asyncio.Redis. None이면 락 없이 (True, None) 반환(비활성).
    """
    if client is None:
        return (True, None)
    key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
    token = str(uuid.uuid4())
    try:
        ok = await client.set(key, token, nx=True, ex=TRIGGER_LOCK_TTL_SECONDS)
        return (bool(ok), token if ok else None)
    except Exception as e:
        logger.warning(
            "Trigger lock acquire failed (college=%s): %s", college_code, e, exc_info=True
        )
        raise RedisLockUnavailableError("Redis unavailable") from e


async def release_trigger_lock(
    client: Any, college_code: str, token: str
) -> bool:
    """
    락 해제(소유자만). Lua compare-and-del. client는 redis.asyncio.Redis.
    반환: True=삭제됨, False=소유자 아님 또는 이미 없음.
    """
    if client is None or not token:
        return False
    key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
    try:
        n = await client.eval(LUA_RELEASE_IF_OWNER, 1, key, token)
        return n == 1
    except Exception as e:
        logger.warning(
            "Trigger lock release failed (college=%s): %s", college_code, e, exc_info=True
        )
        return False


def release_trigger_lock_sync(college_code: str, lock_token: str | None) -> None:
    """
    단과대별 크롤 트리거 락 해제(소유자만). 워커 완료/예외 시 호출.
    lock_token이 None이면 no-op(레거시 호출 방지). 동기 Redis 사용(Celery 워커 환경).
    """
    if not lock_token:
        return
    from app.core.config import settings

    if not settings.redis_url:
        return
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        key = f"{TRIGGER_LOCK_KEY_PREFIX}{college_code}"
        client.eval(LUA_RELEASE_IF_OWNER, 1, key, lock_token)
        client.close()
    except Exception as e:
        logger.warning(
            "Trigger lock release failed (college=%s): %s", college_code, e, exc_info=True
        )


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
