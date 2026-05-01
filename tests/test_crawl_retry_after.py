"""Unit tests for Retry-After parsing (429)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.crawl.runtime import (
    CRAWL_RETRY_BASE_SEC,
    CRAWL_RETRY_MAX_SEC,
    get_crawl_retry_wait,
    parse_retry_after_seconds,
)


def test_parse_retry_after_delta_seconds():
    class Res:
        headers = {"Retry-After": "30"}

    assert parse_retry_after_seconds(Res()) == 30.0


def test_parse_retry_after_delta_seconds_capped_min():
    class Res:
        headers = {"Retry-After": "0"}

    assert parse_retry_after_seconds(Res()) == CRAWL_RETRY_BASE_SEC


def test_parse_retry_after_delta_seconds_capped_max():
    class Res:
        headers = {"Retry-After": "99999"}

    assert parse_retry_after_seconds(Res()) == CRAWL_RETRY_MAX_SEC


def test_parse_retry_after_http_date_future():
    future = datetime.now(UTC) + timedelta(seconds=45)

    class Res:
        headers = {"Retry-After": future.strftime("%a, %d %b %Y %H:%M:%S GMT")}

    got = parse_retry_after_seconds(Res())
    assert got is not None
    assert 40 <= got <= 50


def test_parse_retry_after_http_date_past_returns_none():
    past = datetime.now(UTC) - timedelta(seconds=60)

    class Res:
        headers = {"Retry-After": past.strftime("%a, %d %b %Y %H:%M:%S GMT")}

    assert parse_retry_after_seconds(Res()) is None


def test_parse_retry_after_absent_returns_none():
    class Res:
        headers = {}

    assert parse_retry_after_seconds(Res()) is None


def test_parse_retry_after_invalid_returns_none():
    class Res:
        headers = {"Retry-After": "not-a-number"}

    assert parse_retry_after_seconds(Res()) is None


def test_parse_retry_after_none_response_returns_none():
    assert parse_retry_after_seconds(None) is None


def test_get_crawl_retry_wait_429_with_retry_after_uses_value():
    class DummyHttpError(Exception):
        response: Any | None = None

    class Res:
        headers = {"Retry-After": "20"}
        status_code = 429

    exc = DummyHttpError()
    exc.response = Res()
    from unittest.mock import MagicMock

    from tenacity import RetryCallState

    state = MagicMock(spec=RetryCallState)
    state.outcome = MagicMock()
    state.outcome.exception = lambda: exc
    got = get_crawl_retry_wait(state)
    assert got == 20.0


def test_get_crawl_retry_wait_non_429_delegates_to_fallback(monkeypatch):
    from app.services.crawl import runtime

    fallback_ret = 7.0

    def _fake_wait(_state):
        return fallback_ret

    monkeypatch.setattr(runtime, "_crawl_retry_wait", _fake_wait)

    class DummyHttpError(Exception):
        response: Any | None = None

    class Res:
        headers = {}
        status_code = 503

    exc = DummyHttpError()
    exc.response = Res()
    from unittest.mock import MagicMock

    state = MagicMock()
    state.outcome = MagicMock()
    state.outcome.exception = lambda: exc
    got = get_crawl_retry_wait(state)
    assert got == fallback_ret


def test_sync_downloader_retry_middleware_uses_retry_after_for_429(monkeypatch):
    from app.services.crawl.downloader_middleware import DownloadRequest, SyncRetryMiddleware
    from requests import Response
    from requests.exceptions import HTTPError

    sleeps: list[float] = []
    monkeypatch.setattr("app.services.crawl.downloader_middleware.time.sleep", lambda s: sleeps.append(s))

    resp = Response()
    resp.status_code = 429
    resp.headers["Retry-After"] = "12"
    exc = HTTPError("429", response=resp)
    middleware = SyncRetryMiddleware(
        max_attempts=3,
        backoff_base_seconds=0.1,
        backoff_max_seconds=1.0,
        retry_403_hosts=set(),
    )

    should_retry = middleware.process_exception(
        DownloadRequest(url="https://example.com/1", timeout=1),
        exc,
        attempt=1,
    )

    assert should_retry is True
    assert sleeps == [12.0]
