"""Read-through 캐시. Redis 키 prefix + TTL. 캐시 가능한 조회용. Redis 장애 시 fail-open(캐시 스킵)."""

import json
import logging
from typing import Any, cast

from redis.asyncio import Redis as RedisAsyncio

from app.core.config import settings

logger = logging.getLogger(__name__)


def _cache_key(*parts: str) -> str:
    prefix = (getattr(settings, "read_cache_key_prefix", None) or "read_cache:").strip()
    return prefix + ":".join(str(p) for p in parts)


async def get_cached(client: RedisAsyncio | None, *key_parts: str) -> dict[str, Any] | None:
    """
    Redis에서 캐시 조회. key = prefix + key_parts. JSON 파싱 후 dict 반환.
    client가 None이거나 예외 시 None (fail-open).
    """
    if client is None:
        return None
    key = _cache_key(*key_parts)
    try:
        raw = await client.get(key)
    except Exception as e:
        logger.debug("read_cache get failed: key=%s error=%s", key, e)
        return None
    if raw is None:
        return None
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return cast(dict[str, Any], parsed)
    return None


async def set_cached(
    client: RedisAsyncio | None,
    ttl_seconds: int,
    *key_parts: str,
    value: dict[str, Any],
) -> None:
    """
    Redis에 캐시 저장. key = prefix + key_parts, value = JSON. ttl_seconds 적용.
    client가 None이거나 예외 시 무시 (fail-open).
    """
    if client is None:
        return
    key = _cache_key(*key_parts)
    try:
        payload = json.dumps(value, ensure_ascii=False)
        await client.setex(key, ttl_seconds, payload)
    except Exception as e:
        logger.debug("read_cache set failed: key=%s error=%s", key, e)
