"""notice_dates, link_dedupe, html_image_extract 유틸 단위 테스트."""

from __future__ import annotations

from app.services.crawlers.html_image_extract import extract_images_from_container
from app.services.crawlers.link_dedupe import dedupe_link_dicts_by_url
from app.services.crawlers.notice_dates import normalize_notice_date
from bs4 import BeautifulSoup


def test_normalize_notice_date_korean() -> None:
    assert normalize_notice_date("2024년 3월 5일") == "2024.03.05"
    assert normalize_notice_date("2024-12-25") == "2024.12.25"
    assert normalize_notice_date("no date here") == "no date here"


def test_normalize_notice_date_english() -> None:
    assert normalize_notice_date("Feb 19, 2026", locale="en") == "2026.02.19"
    assert normalize_notice_date("Jan 1, 2025", locale="en") == "2025.01.01"


def test_normalize_notice_date_en_falls_back_korean() -> None:
    assert normalize_notice_date("2024년 1월 2일", locale="en") == "2024.01.02"


def test_normalize_notice_date_loose_digits() -> None:
    assert normalize_notice_date("x 2024 12 25 y", loose_digit_fallback=True) == "2024.12.25"


def test_normalize_notice_date_split_tokens() -> None:
    from app.services.crawlers.notice_dates import normalize_notice_date_split_tokens

    assert normalize_notice_date_split_tokens("2024-03-05") == "2024.03.05"
    assert normalize_notice_date_split_tokens("2024년 12월 25일") == "2024.12.25"


def test_dedupe_link_dicts_by_url() -> None:
    raw = [
        {"url": "https://a.com/1", "no": "1"},
        {"url": "https://a.com/1", "no": "2"},
        {"url": "https://a.com/2", "no": "3"},
        {"url": "", "no": "4"},
    ]
    out = dedupe_link_dicts_by_url(raw)
    assert len(out) == 2
    assert out[0]["no"] == "1"
    assert out[1]["url"] == "https://a.com/2"


def test_extract_images_from_container_url_and_skips_icon() -> None:
    html = '<div id="c"><img src="/x.png"/><img src="/icon-btn.png"/></div>'
    soup = BeautifulSoup(html, "html.parser")
    div = soup.find("div", id="c")
    assert div is not None
    imgs = extract_images_from_container(div, "https://site.example/base/")
    assert len(imgs) == 1
    assert imgs[0]["type"] == "url"
    assert "x.png" in imgs[0]["data"]
    assert div.find("img") is None


def test_extract_images_from_container_data_orig_src() -> None:
    html = '<div id="c"><img src="/thumb" data-orig-src="/full.jpg"/></div>'
    soup = BeautifulSoup(html, "html.parser")
    div = soup.find("div", id="c")
    assert div is not None
    imgs = extract_images_from_container(div, "https://site.example/", prefer_data_orig_src=True)
    assert len(imgs) == 1
    assert "full.jpg" in imgs[0]["data"]
