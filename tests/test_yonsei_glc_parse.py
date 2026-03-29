"""GLC 파서·HtmlTooLarge 예외 정책."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from app.core.crawl_http import HtmlTooLargeError
from app.services.crawlers.yonsei_glc import parse_glc_detail_from_html, scrape_glc_detail
from requests.exceptions import RequestException


def test_parse_glc_detail_from_html_minimal() -> None:
    html = """
    <html><body>
    <div class="kboard-title"><h1>Hello</h1></div>
    <div class="detail-date"><div class="detail-value">2024년 3월 5일</div></div>
    <div class="content-view"><p>Body</p></div>
    </body></html>
    """
    r = parse_glc_detail_from_html(html, "https://glc.example/notice/1")
    assert r.title == "Hello"
    assert r.date_str == "2024.03.05"
    assert "Body" in (r.html_content or "")
    assert r.attachments == []


def test_scrape_glc_detail_html_too_large_raises() -> None:
    with patch(
        "app.services.crawlers.yonsei_glc.fetch_html_detail_cached",
        side_effect=HtmlTooLargeError("too big"),
    ):
        with pytest.raises(RequestException):
            scrape_glc_detail("https://glc.example/x")
