"""
호스트(도메인)별 Rate Limiting. 크롤 시 호스트당 최소 요청 간격을 독립적으로 적용.
동시에 여러 호스트를 크롤해도 호스트별로 지연이 따로 적용된다.
Redis + Lua 기반 분산 limiter 지원. Redis 미설정/실패 시 인메모리 HostRateLimiter로 degrade.
"""

import asyncio
import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

RATE_LIMIT_KEY_PREFIX = "dicee:rate_limit:"
RATE_LIMIT_TTL_SECONDS = 86400  # 24h (ADR)

# Lua: 마지막 허용 시간 조회·갱신·대기량 계산 원자 실행. KEYS[1]=key, ARGV[1]=now, ARGV[2]=min_interval_sec
LUA_RATE_LIMIT = """
local now = tonumber(ARGV[1])
local min_int = tonumber(ARGV[2])
local last = tonumber(redis.call('GET', KEYS[1]) or 0)
local wait_sec = math.max(0, min_int - (now - last))
local new_time = now + wait_sec
redis.call('SET', KEYS[1], tostring(new_time), 'EX', 86400)
return tostring(wait_sec)
"""


def host_from_url(url: str) -> str:
    """URL에서 호스트(네트워크 위치) 추출. 빈 URL은 '' 반환."""
    if not url or not url.strip():
        return ""
    try:
        parsed = urlparse(url)
        return (parsed.netloc or "").strip().lower() or ""
    except (ValueError, AttributeError):
        return ""


class HostRateLimiter:
    """
    호스트별 최소 요청 간격(min_interval_sec)을 적용하는 rate limiter.
    동기(wait_sync) / 비동기(wait_async) 모두 지원.
    """

    __slots__ = ("min_interval_sec", "_last", "_lock")

    def __init__(self, min_interval_sec: float):
        self.min_interval_sec = min_interval_sec
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def wait_sync(self, host: str) -> None:
        """동기: 호스트에 대해 min_interval_sec 이상 경과할 때까지 대기."""
        if not host:
            return
        now = time.monotonic()
        last = self._last.get(host, 0.0)
        wait_sec = self.min_interval_sec - (now - last)
        if wait_sec > 0:
            time.sleep(wait_sec)
        self._last[host] = time.monotonic()

    async def wait_async(self, host: str) -> None:
        """비동기: 호스트에 대해 min_interval_sec 이상 경과할 때까지 대기."""
        if not host:
            return
        async with self._lock:
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            wait_sec = max(0.0, self.min_interval_sec - (now - last))
            self._last[host] = now + wait_sec
        if wait_sec > 0:
            await asyncio.sleep(wait_sec)


class RedisHostRateLimiterSync:
    """
    호스트별 최소 요청 간격을 Redis + Lua로 적용(다중 워커 공유).
    Redis 미설정/실패 시 내부 HostRateLimiter로 degrade.
    """

    __slots__ = ("min_interval_sec", "_client", "_fallback")

    def __init__(self, min_interval_sec: float, redis_url: str | None = None):
        self.min_interval_sec = min_interval_sec
        self._fallback = HostRateLimiter(min_interval_sec)
        self._client = None
        if redis_url and (redis_url or "").strip():
            try:
                import redis
                self._client = redis.Redis.from_url(
                    redis_url.strip(), decode_responses=True
                )
            except Exception as e:
                logger.warning(
                    "Redis rate limit client init failed; using in-memory fallback: %s",
                    e,
                )

    def wait_sync(self, host: str) -> None:
        """동기: 호스트에 대해 min_interval_sec 이상 경과할 때까지 대기. Redis 실패 시 fallback."""
        if not host:
            return
        if self._client is None:
            self._fallback.wait_sync(host)
            return
        key = f"{RATE_LIMIT_KEY_PREFIX}{host}"
        try:
            now = time.monotonic()
            result = self._client.eval(
                LUA_RATE_LIMIT,
                1,
                key,
                str(now),
                str(self.min_interval_sec),
            )
            wait_sec = float(result)
            if wait_sec > 0:
                time.sleep(wait_sec)
        except Exception as e:
            logger.debug(
                "Redis rate limit failed (host=%s); using fallback: %s", host, e
            )
            self._fallback.wait_sync(host)


def get_host_rate_limiter_sync(min_interval_sec: float):
    """동기 크롤용 limiter. Redis URL 있으면 RedisHostRateLimiterSync, 없으면 HostRateLimiter."""
    try:
        from app.core.config import settings
        redis_url = getattr(settings, "redis_url", None) or ""
        if (redis_url or "").strip():
            return RedisHostRateLimiterSync(min_interval_sec, redis_url.strip())
    except Exception:
        pass
    return HostRateLimiter(min_interval_sec)


class RedisHostRateLimiterAsync:
    """
    호스트별 최소 요청 간격을 Redis + Lua로 적용(다중 워커 공유, 비동기).
    Redis 미설정/실패 시 내부 HostRateLimiter로 degrade.
    """

    __slots__ = ("min_interval_sec", "_client", "_fallback")

    def __init__(self, min_interval_sec: float, redis_url: str | None = None):
        self.min_interval_sec = min_interval_sec
        self._fallback = HostRateLimiter(min_interval_sec)
        self._client = None
        if redis_url and (redis_url or "").strip():
            try:
                import redis.asyncio as redis

                self._client = redis.Redis.from_url(
                    redis_url.strip(),
                    decode_responses=True,
                )
            except Exception as e:
                logger.warning(
                    "Redis async rate limit client init failed; using in-memory fallback: %s",
                    e,
                )

    async def wait_async(self, host: str) -> None:
        """비동기: 호스트에 대해 min_interval_sec 이상 경과할 때까지 대기. Redis 실패 시 fallback."""
        if not host:
            return
        if self._client is None:
            await self._fallback.wait_async(host)
            return
        key = f"{RATE_LIMIT_KEY_PREFIX}{host}"
        try:
            now = time.monotonic()
            result = await self._client.eval(
                LUA_RATE_LIMIT,
                1,
                key,
                str(now),
                str(self.min_interval_sec),
            )
            wait_sec = float(result)
            if wait_sec > 0:
                await asyncio.sleep(wait_sec)
        except Exception as e:
            logger.debug(
                "Redis async rate limit failed (host=%s); using fallback: %s",
                host,
                e,
            )
            await self._fallback.wait_async(host)


def get_host_rate_limiter_async(min_interval_sec: float):
    """비동기 크롤용 limiter. Redis URL 있으면 RedisHostRateLimiterAsync, 없으면 HostRateLimiter."""
    try:
        from app.core.config import settings

        redis_url = getattr(settings, "redis_url", None) or ""
        if (redis_url or "").strip():
            return RedisHostRateLimiterAsync(min_interval_sec, redis_url.strip())
    except Exception:
        pass
    return HostRateLimiter(min_interval_sec)
