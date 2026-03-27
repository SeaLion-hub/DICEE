"""Unit tests for requests-based HTML fetcher (no network)."""

from __future__ import annotations

import pytest
import responses
from app.core.crawl_http import HtmlTooLargeError, fetch_html


@responses.activate
def test_fetch_html_content_length_too_large_raises() -> None:
    url = "https://example.com/too-large"
    responses.add(
        method=responses.GET,
        url=url,
        body=b"ok",
        status=200,
        headers={"Content-Length": "999999"},
    )
    with pytest.raises(HtmlTooLargeError):
        fetch_html(url, max_bytes=10)


@responses.activate
def test_fetch_html_stream_accumulated_too_large_raises_when_no_content_length() -> None:
    url = "https://example.com/stream-too-large"
    responses.add(
        method=responses.GET,
        url=url,
        body=b"x" * 21,
        status=200,
        headers={},
    )
    with pytest.raises(HtmlTooLargeError):
        fetch_html(url, max_bytes=20)


@responses.activate
def test_fetch_html_stream_accumulated_too_large_ignores_invalid_content_length() -> None:
    """Header is untrusted; fallback to streaming guard."""
    url = "https://example.com/bad-content-length"
    responses.add(
        method=responses.GET,
        url=url,
        body=b"x" * 21,
        status=200,
        headers={"Content-Length": "not-a-number"},
    )
    with pytest.raises(HtmlTooLargeError):
        fetch_html(url, max_bytes=20)


@responses.activate
def test_fetch_html_non_2xx_raises() -> None:
    url = "https://example.com/404"
    responses.add(
        method=responses.GET,
        url=url,
        body=b"nope",
        status=404,
    )
    with pytest.raises(Exception):
        fetch_html(url, max_bytes=1024)

