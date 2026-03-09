"""Downloader middleware stack inspired by Scrapy's request/response hooks."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import httpx
from requests.exceptions import RequestException
from requests.exceptions import Timeout as RequestsTimeout

from app.core.config import settings
from app.core.crawl_rate_limit import (
    HostRateLimiter,
    RedisHostRateLimiterAsync,
    get_host_rate_limiter_async,
    get_host_rate_limiter_sync,
    host_from_url,
)
from app.core.crawler_config import CRAWLER_HEADERS
from app.services.crawl_policy import (
    HTTP_RETRY_STATUS_CODES,
    HTTP_RETRY_STATUS_MAX_5XX,
    HTTP_RETRY_STATUS_MIN_5XX,
)

logger = logging.getLogger(__name__)

_NETWORK_RETRY_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    OSError,
    RequestException,
    RequestsTimeout,
    httpx.TimeoutException,
    httpx.HTTPError,
)


@dataclass(slots=True)
class DownloadRequest:
    url: str
    timeout: float
    headers: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DownloadResponse:
    url: str
    body: str
    status_code: int | None = None
    headers: dict[str, Any] = field(default_factory=dict)


class SyncDownloaderMiddleware(Protocol):
    def process_request(self, request: DownloadRequest) -> DownloadRequest:
        ...

    def process_response(self, request: DownloadRequest, response: DownloadResponse) -> DownloadResponse:
        ...

    def process_exception(self, request: DownloadRequest, exc: Exception, attempt: int) -> bool | None:
        ...


class AsyncDownloaderMiddleware(Protocol):
    async def process_request(self, request: DownloadRequest) -> DownloadRequest:
        ...

    async def process_response(self, request: DownloadRequest, response: DownloadResponse) -> DownloadResponse:
        ...

    async def process_exception(self, request: DownloadRequest, exc: Exception, attempt: int) -> bool | None:
        ...


class DefaultHeadersMiddleware:
    """Ensure a browser-like UA and merge caller headers on top of defaults."""

    def process_request(self, request: DownloadRequest) -> DownloadRequest:
        merged = dict(CRAWLER_HEADERS)
        if request.headers:
            merged.update(request.headers)
        request.headers = merged
        return request

    def process_response(self, request: DownloadRequest, response: DownloadResponse) -> DownloadResponse:
        return response

    def process_exception(self, request: DownloadRequest, exc: Exception, attempt: int) -> bool | None:
        return None

    async def process_request_async(self, request: DownloadRequest) -> DownloadRequest:
        return self.process_request(request)

    async def process_response_async(self, request: DownloadRequest, response: DownloadResponse) -> DownloadResponse:
        return response

    async def process_exception_async(self, request: DownloadRequest, exc: Exception, attempt: int) -> bool | None:
        return None


class SyncHostRateLimitMiddleware:
    """Per-host politeness limiter for sync downloader paths."""

    def __init__(self, min_interval_sec: float) -> None:
        self._limiter = get_host_rate_limiter_sync(min_interval_sec)

    def process_request(self, request: DownloadRequest) -> DownloadRequest:
        host = host_from_url(request.url)
        if host:
            self._limiter.wait_sync(host)
        return request

    def process_response(self, request: DownloadRequest, response: DownloadResponse) -> DownloadResponse:
        return response

    def process_exception(self, request: DownloadRequest, exc: Exception, attempt: int) -> bool | None:
        return None


class AsyncHostRateLimitMiddleware:
    """Per-host politeness limiter for async downloader paths."""

    def __init__(self, min_interval_sec: float) -> None:
        self._limiter: HostRateLimiter | RedisHostRateLimiterAsync = get_host_rate_limiter_async(min_interval_sec)

    async def process_request(self, request: DownloadRequest) -> DownloadRequest:
        host = host_from_url(request.url)
        if host:
            await self._limiter.wait_async(host)
        return request

    async def process_response(self, request: DownloadRequest, response: DownloadResponse) -> DownloadResponse:
        return response

    async def process_exception(self, request: DownloadRequest, exc: Exception, attempt: int) -> bool | None:
        return None


class SyncRetryMiddleware:
    """Retry middleware with host-level 403 override for WAF-tuned policies."""

    def __init__(
        self,
        *,
        max_attempts: int,
        backoff_base_seconds: float,
        backoff_max_seconds: float,
        retry_403_hosts: set[str],
    ) -> None:
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._backoff_max = backoff_max_seconds
        self._retry_403_hosts = retry_403_hosts

    def process_request(self, request: DownloadRequest) -> DownloadRequest:
        return request

    def process_response(self, request: DownloadRequest, response: DownloadResponse) -> DownloadResponse:
        return response

    def process_exception(self, request: DownloadRequest, exc: Exception, attempt: int) -> bool | None:
        if attempt >= self._max_attempts:
            return False
        if not _should_retry(request, exc, self._retry_403_hosts):
            return False
        sleep_sec = _retry_backoff_seconds(
            attempt=attempt,
            base=self._backoff_base,
            cap=self._backoff_max,
        )
        time.sleep(sleep_sec)
        return True


class AsyncRetryMiddleware:
    """Async retry middleware mirroring sync retry semantics."""

    def __init__(
        self,
        *,
        max_attempts: int,
        backoff_base_seconds: float,
        backoff_max_seconds: float,
        retry_403_hosts: set[str],
    ) -> None:
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._backoff_max = backoff_max_seconds
        self._retry_403_hosts = retry_403_hosts

    async def process_request(self, request: DownloadRequest) -> DownloadRequest:
        return request

    async def process_response(self, request: DownloadRequest, response: DownloadResponse) -> DownloadResponse:
        return response

    async def process_exception(self, request: DownloadRequest, exc: Exception, attempt: int) -> bool | None:
        if attempt >= self._max_attempts:
            return False
        if not _should_retry(request, exc, self._retry_403_hosts):
            return False
        sleep_sec = _retry_backoff_seconds(
            attempt=attempt,
            base=self._backoff_base,
            cap=self._backoff_max,
        )
        await asyncio.sleep(sleep_sec)
        return True


class SyncDownloaderMiddlewareManager:
    def __init__(self, middlewares: Sequence[SyncDownloaderMiddleware]) -> None:
        self._middlewares = list(middlewares)

    def fetch(
        self,
        request: DownloadRequest,
        sender: Callable[[DownloadRequest], DownloadResponse],
    ) -> DownloadResponse:
        attempt = 1
        while True:
            req = request
            for middleware in self._middlewares:
                req = middleware.process_request(req)
            try:
                response = sender(req)
            except Exception as exc:
                should_retry = False
                handled = False
                for middleware in reversed(self._middlewares):
                    decision = middleware.process_exception(req, exc, attempt)
                    if decision is None:
                        continue
                    should_retry = bool(decision)
                    handled = True
                    break
                if should_retry:
                    attempt += 1
                    continue
                if handled:
                    raise
                raise
            for middleware in reversed(self._middlewares):
                response = middleware.process_response(req, response)
            return response


class AsyncDownloaderMiddlewareManager:
    def __init__(self, middlewares: Sequence[AsyncDownloaderMiddleware]) -> None:
        self._middlewares = list(middlewares)

    async def fetch(
        self,
        request: DownloadRequest,
        sender: Callable[[DownloadRequest], Awaitable[DownloadResponse]],
    ) -> DownloadResponse:
        attempt = 1
        while True:
            req = request
            for middleware in self._middlewares:
                req = await middleware.process_request(req)
            try:
                response = await sender(req)
            except Exception as exc:
                should_retry = False
                handled = False
                for middleware in reversed(self._middlewares):
                    decision = await middleware.process_exception(req, exc, attempt)
                    if decision is None:
                        continue
                    should_retry = bool(decision)
                    handled = True
                    break
                if should_retry:
                    attempt += 1
                    continue
                if handled:
                    raise
                raise
            for middleware in reversed(self._middlewares):
                response = await middleware.process_response(req, response)
            return response


@lru_cache(maxsize=1)
def get_default_sync_downloader_manager() -> SyncDownloaderMiddlewareManager:
    retry_403_hosts = _parse_retry_403_hosts(settings.crawl_retry_403_hosts)
    return SyncDownloaderMiddlewareManager(
        [
            DefaultHeadersMiddleware(),
            SyncHostRateLimitMiddleware(settings.polite_delay_seconds),
            SyncRetryMiddleware(
                max_attempts=settings.crawl_http_retry_max_attempts,
                backoff_base_seconds=settings.crawl_http_retry_backoff_base_seconds,
                backoff_max_seconds=settings.crawl_http_retry_backoff_max_seconds,
                retry_403_hosts=retry_403_hosts,
            ),
        ]
    )


@lru_cache(maxsize=1)
def get_default_async_downloader_manager() -> AsyncDownloaderMiddlewareManager:
    retry_403_hosts = _parse_retry_403_hosts(settings.crawl_retry_403_hosts)
    return AsyncDownloaderMiddlewareManager(
        [
            _AsyncHeadersMiddleware(),
            AsyncHostRateLimitMiddleware(settings.polite_delay_seconds),
            AsyncRetryMiddleware(
                max_attempts=settings.crawl_http_retry_max_attempts,
                backoff_base_seconds=settings.crawl_http_retry_backoff_base_seconds,
                backoff_max_seconds=settings.crawl_http_retry_backoff_max_seconds,
                retry_403_hosts=retry_403_hosts,
            ),
        ]
    )


def reset_default_downloader_managers() -> None:
    get_default_sync_downloader_manager.cache_clear()
    get_default_async_downloader_manager.cache_clear()


class _AsyncHeadersMiddleware:
    """Async facade for default header middleware."""

    def __init__(self) -> None:
        self._delegate = DefaultHeadersMiddleware()

    async def process_request(self, request: DownloadRequest) -> DownloadRequest:
        return self._delegate.process_request(request)

    async def process_response(self, request: DownloadRequest, response: DownloadResponse) -> DownloadResponse:
        return response

    async def process_exception(self, request: DownloadRequest, exc: Exception, attempt: int) -> bool | None:
        return None


def _retry_backoff_seconds(*, attempt: int, base: float, cap: float) -> float:
    exp = min(cap, base * (2 ** max(0, attempt - 1)))
    jitter = random.uniform(0.0, min(0.5, exp))
    return exp + jitter


def _parse_retry_403_hosts(raw: str) -> set[str]:
    return {h.strip().lower() for h in (raw or "").split(",") if h.strip()}


def _exception_status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "status_code"):
        try:
            return int(response.status_code)
        except (TypeError, ValueError):
            return None
    return None


def _should_retry(request: DownloadRequest, exc: BaseException, retry_403_hosts: set[str]) -> bool:
    code = _exception_status_code(exc)
    if code is not None:
        if code == 403:
            host = host_from_url(request.url)
            return host in retry_403_hosts or bool(request.meta.get("retry_403", False))
        if code in HTTP_RETRY_STATUS_CODES:
            return True
        return HTTP_RETRY_STATUS_MIN_5XX <= code <= HTTP_RETRY_STATUS_MAX_5XX
    return isinstance(exc, _NETWORK_RETRY_EXCEPTIONS)

