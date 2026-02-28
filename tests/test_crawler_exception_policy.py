from unittest.mock import MagicMock

import pytest
from requests.exceptions import RequestException

from app.core.crawl_http import HtmlTooLargeError


def test_yonsei_engineering_sync_propagates_request_exception(monkeypatch):
    from app.services.crawlers import yonsei_engineering as crawler

    def _raise_request_exception(*args, **kwargs):
        raise RequestException("network error")

    monkeypatch.setattr(crawler, "fetch_html", _raise_request_exception)

    with pytest.raises(RequestException):
        crawler.scrape_yonsei_engineering_precise("https://example.com/detail")


@pytest.mark.asyncio
async def test_yonsei_engineering_async_propagates_html_too_large(monkeypatch):
    from app.services.crawlers import yonsei_engineering as crawler

    async def _raise_html_too_large(*args, **kwargs):
        raise HtmlTooLargeError("too large")

    monkeypatch.setattr(crawler, "fetch_html_async", _raise_html_too_large)

    with pytest.raises(HtmlTooLargeError):
        await crawler.scrape_yonsei_engineering_precise_async(
            MagicMock(),
            "https://example.com/detail",
        )


@pytest.mark.asyncio
async def test_yonsei_business_async_propagates_html_too_large(monkeypatch):
    from app.services.crawlers import yonsei_business as crawler

    async def _raise_html_too_large(*args, **kwargs):
        raise HtmlTooLargeError("too large")

    monkeypatch.setattr(crawler, "fetch_html_async", _raise_html_too_large)

    with pytest.raises(HtmlTooLargeError):
        await crawler.scrape_business_detail_async(
            MagicMock(),
            "https://example.com/detail",
        )
