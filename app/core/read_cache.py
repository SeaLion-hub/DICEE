"""Read-through 캐시. Redis 키 prefix + TTL. 캐시 가능한 조회용. Redis 장애 시 fail-open(캐시 스킵)."""

import asyncio
import json
import logging
from typing import Any, cast

from redis.asyncio import Redis as RedisAsyncio

from app.core.config import settings
from app.core.redis import (
    get_cache_with_soft_ttl as _redis_get_soft,
)
from app.core.redis import (
    release_cache_lock as _redis_release_lock,
)
from app.core.redis import (
    set_cache_with_soft_ttl as _redis_set_soft,
)

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


# --- Soft TTL + Mutex (Cache Stampede 방어). API는 read_cache만 사용 ---


async def get_cached_with_soft_ttl(
    client: RedisAsyncio | None, *key_parts: str
) -> tuple[dict[str, Any] | None, bool, str | None]:
    """
    Soft TTL 캐시 조회. key = prefix + key_parts.
    반환: (data, should_refresh, lock_token). lock_token은 갱신 후 release_cached_lock에 전달.
    """
    if client is None:
        return None, True, None
    key = _cache_key(*key_parts)
    lock_ttl = getattr(settings, "read_cache_lock_ttl_seconds", 10)
    data, should_refresh, token = await _redis_get_soft(client, key, lock_ttl_seconds=lock_ttl)
    if data is not None and not isinstance(data, dict):
        return None, should_refresh, token
    return cast("dict[str, Any] | None", data), should_refresh, token


async def set_cached_with_soft_ttl(
    client: RedisAsyncio | None,
    *key_parts: str,
    value: dict[str, Any],
) -> None:
    """Soft TTL로 캐시 저장. soft_ttl < hard_ttl은 config 검증으로 보장."""
    if client is None:
        return
    key = _cache_key(*key_parts)
    soft = getattr(settings, "read_cache_soft_ttl_seconds", 20)
    hard = getattr(settings, "read_cache_ttl_seconds", 60)
    await _redis_set_soft(client, key, value, soft, hard)


async def release_cached_lock(client: RedisAsyncio | None, *key_parts: str, token: str) -> None:
    """캐시 락 조기 해제. token은 get_cached_with_soft_ttl 반환값."""
    if client is None or not token:
        return
    key = _cache_key(*key_parts)
    await _redis_release_lock(client, key, token)


async def wait_for_cached(
    client: RedisAsyncio | None, wait_ms: int, *key_parts: str
) -> tuple[dict[str, Any] | None, bool, str | None]:
    """Hard miss + 락 미획득 시 짧게 대기 후 재조회."""
    if wait_ms > 0:
        await asyncio.sleep(wait_ms / 1000.0)
    return await get_cached_with_soft_ttl(client, *key_parts)
