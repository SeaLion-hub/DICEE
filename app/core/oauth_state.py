"""OAuth 1회용 state 저장/검증. CSRF 방어용. Redis 키: dicee:oauth_state:{state}, TTL 600초."""

import logging
import uuid

from redis.asyncio import Redis as RedisAsyncio

logger = logging.getLogger(__name__)

OAUTH_STATE_KEY_PREFIX = "dicee:oauth_state:"
OAUTH_STATE_TTL_SECONDS = 600


async def store_state(client: RedisAsyncio | None, state: str) -> bool:
    """state를 Redis에 저장. 성공 시 True, client가 None이면 False."""
    if client is None or not (state or "").strip():
        return False
    key = f"{OAUTH_STATE_KEY_PREFIX}{state.strip()}"
    try:
        await client.set(key, "1", ex=OAUTH_STATE_TTL_SECONDS)
        return True
    except Exception:
        logger.warning("OAuth state store failed", exc_info=True)
        return False


async def consume_state(client: RedisAsyncio | None, state: str) -> bool:
    """
    state가 존재하면 삭제 후 True 반환(1회용 소비). 없거나 이미 소비됐으면 False.
    client가 None이면 False.
    """
    if client is None or not (state or "").strip():
        return False
    key = f"{OAUTH_STATE_KEY_PREFIX}{state.strip()}"
    try:
        deleted = await client.delete(key)
        return deleted > 0
    except Exception:
        logger.warning("OAuth state consume failed", exc_info=True)
        return False


def generate_state() -> str:
    """1회용 state 값 생성(URL-safe)."""
    return str(uuid.uuid4())
