"""Async downloader middleware: retry·rate limit·default manager cache."""

import pytest
from requests import Response
from requests.exceptions import HTTPError


def _http_error(status_code: int) -> HTTPError:
    resp = Response()
    resp.status_code = status_code
    return HTTPError(str(status_code), response=resp)


@pytest.mark.asyncio
async def test_async_downloader_retry_403_allowed_host_retries_once() -> None:
    from app.services.crawl.downloader_middleware import (
        AsyncDownloaderMiddlewareManager,
        AsyncRetryMiddleware,
        DownloadRequest,
        DownloadResponse,
    )

    calls = {"count": 0}

    async def _sender(_request: DownloadRequest) -> DownloadResponse:
        calls["count"] += 1
        if calls["count"] == 1:
            raise _http_error(403)
        return DownloadResponse(url="https://example.com/detail/1", body="ok")

    manager = AsyncDownloaderMiddlewareManager(
        [
            AsyncRetryMiddleware(
                max_attempts=3,
                backoff_base_seconds=0.0,
                backoff_max_seconds=0.0,
                retry_403_hosts={"example.com"},
            )
        ]
    )
    out = await manager.fetch(
        DownloadRequest(url="https://example.com/detail/1", timeout=1.0),
        _sender,
    )
    assert out.body == "ok"
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_async_downloader_retry_403_non_allowed_host_does_not_retry() -> None:
    from app.services.crawl.downloader_middleware import (
        AsyncDownloaderMiddlewareManager,
        AsyncRetryMiddleware,
        DownloadRequest,
    )

    calls = {"count": 0}

    async def _sender(_request: DownloadRequest):
        calls["count"] += 1
        raise _http_error(403)

    manager = AsyncDownloaderMiddlewareManager(
        [
            AsyncRetryMiddleware(
                max_attempts=3,
                backoff_base_seconds=0.0,
                backoff_max_seconds=0.0,
                retry_403_hosts=set(),
            )
        ]
    )

    with pytest.raises(HTTPError):
        await manager.fetch(DownloadRequest(url="https://example.com/detail/1", timeout=1.0), _sender)

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_async_host_rate_limit_middleware_calls_wait_async(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.crawl import downloader_middleware as dm

    waited: list[str] = []

    class _FakeLimiter:
        async def wait_async(self, host: str) -> None:
            waited.append(host)

    monkeypatch.setattr(dm, "get_host_rate_limiter_async", lambda _sec: _FakeLimiter())
    mw = dm.AsyncHostRateLimitMiddleware(0.01)
    req = dm.DownloadRequest(url="https://foo.example/detail", timeout=1.0)
    out = await mw.process_request(req)
    assert out is req
    assert waited == ["foo.example"]


def test_reset_default_downloader_managers_clears_lru_caches() -> None:
    from app.services.crawl.downloader_middleware import (
        get_default_async_downloader_manager,
        get_default_sync_downloader_manager,
        reset_default_downloader_managers,
    )

    try:
        a1 = get_default_async_downloader_manager()
        s1 = get_default_sync_downloader_manager()
        assert get_default_async_downloader_manager() is a1
        assert get_default_sync_downloader_manager() is s1
        reset_default_downloader_managers()
        a2 = get_default_async_downloader_manager()
        s2 = get_default_sync_downloader_manager()
        assert a2 is not a1
        assert s2 is not s1
    finally:
        reset_default_downloader_managers()
