"""
일반 HTTP API용 Rate Limiter.

특징:
- Redis + Lua 기반 분산 카운터 (슬라이딩 윈도우 유사) 우선.
- Redis 미설정/장애 시: api_rate_limit_require_redis=True면 503(RateLimitUnavailableError),
  False면 프로세스 로컬 인메모리 카운터로 degrade(멀티 인스턴스에서는 방어력 감소).
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import time
from collections.abc import Awaitable
from typing import Any, Final, cast

from redis.asyncio import Redis as RedisAsyncio

logger = logging.getLogger(__name__)

API_RATE_LIMIT_KEY_PREFIX: Final[str] = "dicee:api_rate:"

# 인메모리 fallback: 샤드 락 + 샤드당 dict + 만료 min-heap. 전역 단일 락/전체 순회 제거.
_NUM_SHARDS: Final[int] = 32
_MAX_INMEMORY_KEYS: Final[int] = 100_000
_PER_SHARD_CAP: Final[int] = max(1, _MAX_INMEMORY_KEYS // _NUM_SHARDS)

_shard_locks: list[asyncio.Lock] = [asyncio.Lock() for _ in range(_NUM_SHARDS)]
# 샤드별 (identifier -> (window_start, count))
_shard_counts: list[dict[str, tuple[float, int]]] = [dict() for _ in range(_NUM_SHARDS)]
# 샤드별 min-heap of (window_start, identifier). 만료 청소 시 O(log N) pop.
_shard_heaps: list[list[tuple[float, str]]] = [list() for _ in range(_NUM_SHARDS)]


def _shard_index(identifier: str) -> int:
    return hash(identifier) % _NUM_SHARDS


class RateLimitExceededError(Exception):
    """Rate limit 초과 시 사용 가능한 예외."""


class RateLimitUnavailableError(Exception):
    """Redis 필수 모드에서 Redis 미설정/장애로 레이트리밋 검사를 수행할 수 없을 때. 라우터에서 503 변환."""


def _evict_expired_shard(shard: int, now: float, window_seconds: int) -> None:
    """샤드에서 만료된 항목만 heap에서 꺼내 삭제. 캡 여부와 관계없이 만료된 항목은 매 요청마다 제거하여 힙 누적 방지."""
    counts = _shard_counts[shard]
    heap = _shard_heaps[shard]
    cutoff = now - window_seconds
    while heap and heap[0][0] < cutoff:
        ws, id_ = heapq.heappop(heap)
        if id_ in counts and counts[id_][0] == ws:
            del counts[id_]


async def _check_rate_limit_inmemory(
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> bool:
    """프로세스 로컬 인메모리 카운터. 샤드 락 + 만료 min-heap으로 경합·tail latency 완화."""
    now = time.monotonic()
    shard = _shard_index(identifier)
    async with _shard_locks[shard]:
        counts = _shard_counts[shard]
        heap = _shard_heaps[shard]
        _evict_expired_shard(shard, now, window_seconds)
        if len(counts) >= _PER_SHARD_CAP:
            # 만료 후에도 가득 차면 가장 오래된 항목부터 heap으로 제거
            while heap and len(counts) >= _PER_SHARD_CAP:
                ws, id_ = heapq.heappop(heap)
                if id_ in counts and counts[id_][0] == ws:
                    del counts[id_]

        was_new = identifier not in counts
        window_start, count = counts.get(identifier, (now, 0))
        window_reset = now - window_start >= window_seconds
        if window_reset:
            window_start = now
            count = 0
        count += 1
        counts[identifier] = (window_start, count)
        if was_new or window_reset:
            heapq.heappush(heap, (window_start, identifier))
        return count <= max_requests


_LUA_API_RATE_LIMIT: Final[str] = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local max_req = tonumber(ARGV[2])
local current = redis.call('INCR', key)
if current == 1 then
  redis.call('EXPIRE', key, window)
end
return current
"""


async def check_rate_limit(
    client: RedisAsyncio | None,
    *,
    identifier: str,
    max_requests: int,
    window_seconds: int,
    require_redis: bool = False,
) -> bool:
    """
    주어진 identifier에 대해 window 내 호출 횟수가 max_requests를 넘지 않았는지 검사.

    - Redis가 있으면 Lua 스크립트로 분산 카운터 사용.
    - Redis 미설정/장애 시: require_redis=True면 RateLimitUnavailableError(503 변환), False면 인메모리 fallback.

    반환:
        True  - 허용
        False - 차단 (rate limit 초과)
    """
    if max_requests <= 0 or window_seconds <= 0:
        return True

    if client is None:
        if require_redis:
            raise RateLimitUnavailableError(
                "Rate limit requires Redis but client is not configured. "
                "Set REDIS_URL or set api_rate_limit_require_redis=False."
            )
        return await _check_rate_limit_inmemory(identifier, max_requests, window_seconds)

    key = f"{API_RATE_LIMIT_KEY_PREFIX}{identifier}"
    try:
        raw_result = await cast(
            Awaitable[Any],
            client.eval(
                _LUA_API_RATE_LIMIT,
                1,
                key,
                str(window_seconds),
                str(max_requests),
            ),
        )
        result = cast(str, raw_result)
        try:
            current = int(result)
        except (TypeError, ValueError):
            if require_redis:
                raise RateLimitUnavailableError(
                    "Rate limit Redis returned invalid response; require_redis=True."
                ) from None
            logger.debug(
                "api rate limit eval returned non-int (identifier=%s, result=%r); using in-memory fallback",
                identifier,
                result,
            )
            return await _check_rate_limit_inmemory(identifier, max_requests, window_seconds)
        return current <= max_requests
    except RateLimitUnavailableError:
        raise
    except Exception as e:
        if require_redis:
            raise RateLimitUnavailableError("Rate limit Redis failed; require_redis=True.") from e
        logger.debug(
            "api rate limit failed (identifier=%s); using in-memory fallback: %s",
            identifier,
            e,
        )
        return await _check_rate_limit_inmemory(identifier, max_requests, window_seconds)
