"""
일반 HTTP API용 Rate Limiter.

특징:
- Redis + Lua 기반 분산 카운터 (슬라이딩 윈도우 유사) 우선.
- Redis 미설정/장애 시 프로세스 로컬 인메모리 카운터로 degrade.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Final

from redis.asyncio import Redis as RedisAsyncio

logger = logging.getLogger(__name__)

API_RATE_LIMIT_KEY_PREFIX: Final[str] = "dicee:api_rate:"

# 인메모리 fallback용 전역 상태
_inmemory_counts: dict[str, tuple[float, int]] = {}
_inmemory_lock = asyncio.Lock()
_MAX_INMEMORY_KEYS: Final[int] = 100_000


class RateLimitExceededError(Exception):
    """Rate limit 초과 시 사용 가능한 예외."""


async def _check_rate_limit_inmemory(
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> bool:
    """프로세스 로컬 인메모리 카운터 기반 rate limit. 키 수 상한 초과 시 오래된 키 정리."""
    now = time.monotonic()
    async with _inmemory_lock:
        if len(_inmemory_counts) > _MAX_INMEMORY_KEYS:
            cutoff = now - window_seconds
            stale_keys = [k for k, (ws, _) in _inmemory_counts.items() if ws < cutoff]
            for k in stale_keys:
                _inmemory_counts.pop(k, None)

        window_start, count = _inmemory_counts.get(identifier, (now, 0))
        if now - window_start >= window_seconds:
            window_start = now
            count = 0
        count += 1
        _inmemory_counts[identifier] = (window_start, count)
        return count <= max_requests


_LUA_API_RATE_LIMIT: Final[str] = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_req = tonumber(ARGV[3])
local current = tonumber(redis.call('GET', key) or '0')
current = current + 1
redis.call('SET', key, tostring(current), 'EX', window)
if current > max_req then
  return current
end
return current
"""


async def check_rate_limit(
    client: RedisAsyncio | None,
    *,
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> bool:
    """
    주어진 identifier에 대해 window 내 호출 횟수가 max_requests를 넘지 않았는지 검사.

    - Redis가 있으면 Lua 스크립트로 분산 카운터 사용.
    - Redis 미설정/장애 시 프로세스 로컬 인메모리 카운터로 degrade.

    반환:
        True  - 허용
        False - 차단 (rate limit 초과)
    """
    if max_requests <= 0 or window_seconds <= 0:
        # 0 이하 설정은 무제한으로 해석.
        return True

    if client is None:
        return await _check_rate_limit_inmemory(identifier, max_requests, window_seconds)

    key = f"{API_RATE_LIMIT_KEY_PREFIX}{identifier}"
    try:
        now = int(time.time())
        # eval은 Redis 측에서 Lua 스크립트 캐시를 사용하므로 반복 호출해도 됨.
        result = await client.eval(
            _LUA_API_RATE_LIMIT,
            1,
            key,
            str(now),
            str(window_seconds),
            str(max_requests),
        )
        try:
            current = int(result)
        except (TypeError, ValueError):
            # 비정상 응답 시 보수적으로 fallback 사용.
            logger.debug(
                "api rate limit eval returned non-int (identifier=%s, result=%r); using in-memory fallback",
                identifier,
                result,
            )
            return await _check_rate_limit_inmemory(identifier, max_requests, window_seconds)
        return current <= max_requests
    except Exception as e:
        logger.debug(
            "api rate limit failed (identifier=%s); using in-memory fallback: %s",
            identifier,
            e,
        )
        return await _check_rate_limit_inmemory(identifier, max_requests, window_seconds)

