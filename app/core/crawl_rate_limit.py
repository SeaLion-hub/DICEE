"""
호스트(도메인)별 Rate Limiting. 크롤 시 호스트당 최소 요청 간격을 독립적으로 적용.
동시에 여러 호스트를 크롤해도 호스트별로 지연이 따로 적용된다.
"""

import asyncio
import time
from urllib.parse import urlparse


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
