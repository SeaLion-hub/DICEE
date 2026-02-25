"""crawl_payload 순수 함수 검증: URL 파싱, 날짜 형식, 해시, build_notice_payload."""

import uuid
from unittest.mock import patch

from app.services.crawl_payload import (
    _attachments_to_dicts,
    _content_hash_from_title_and_html,
    _external_id_from_url,
    _parse_published_at,
    build_notice_payload,
)


def test_parse_published_at_various_formats():
    """YYYY.MM.DD, YYYY-M-D 등 형식 파싱 및 실패 시 None."""
    dt = _parse_published_at("2024.01.15")
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 15

    dt2 = _parse_published_at("2024-1-5")
    assert dt2 is not None
    assert dt2.day == 5

    assert _parse_published_at("invalid date") is None
    assert _parse_published_at("") is None
    assert _parse_published_at(None) is None


def test_external_id_extraction():
    """쿼리 파라미터·path 세그먼트 추출 및 fallback 시 sha256 앞 32자."""
    assert _external_id_from_url("https://site.com/view?articleNo=123") == "123"
    assert _external_id_from_url("https://site.com/view?no=abc") == "abc"
    assert _external_id_from_url("https://site.com/view?article_no=1") == "1"
    # path 마지막 세그먼트가 alnum이면 그대로 사용
    assert _external_id_from_url("https://site.com/post/abc") == "abc"
    # 해시 fallback: path 세그먼트가 비어있거나 alnum이 아니면 sha256 앞 32자
    fallback_id = _external_id_from_url("https://site.com/post/some-id-123")
    assert len(fallback_id) == 32
    assert fallback_id.isalnum()


def test_content_hash_from_title_and_html():
    """body_text 있으면 HTML 파싱 생략, 없으면 BeautifulSoup으로 텍스트 추출 후 해시."""
    h1 = _content_hash_from_title_and_html("Title", "<p>body</p>", body_text=None)
    h2 = _content_hash_from_title_and_html("Title", "<p>body</p>", body_text="body")
    assert h1 == h2
    assert len(h1) == 64
    assert h1.isalnum()

    empty = _content_hash_from_title_and_html("T", None, body_text=None)
    assert len(empty) == 64


def test_attachments_to_dicts():
    """빈 리스트, 문자열 리스트, dict 리스트, 혼합."""
    assert _attachments_to_dicts([]) == []
    assert _attachments_to_dicts(["a.pdf", "b"]) == [
        {"name": "a.pdf"},
        {"name": "b"},
    ]
    assert _attachments_to_dicts([{"name": "x", "url": "u"}]) == [
        {"name": "x", "url": "u"},
    ]
    assert _attachments_to_dicts(["a", {"name": "b"}]) == [
        {"name": "a"},
        {"name": "b"},
    ]


@patch("app.services.crawl_payload.upload_notice_html")
def test_build_notice_payload_skips_empty_title(mock_upload):
    """title 없음/빈 문자열이면 None."""
    mock_upload.return_value = "https://storage/url"
    college_id = uuid.uuid4()
    assert build_notice_payload(
        college_id, {}, "https://u", "", None, "<p>x</p>", [], [], None, None
    ) is None
    assert build_notice_payload(
        college_id, {}, "https://u", "   ", None, "<p>x</p>", [], [], None, None
    ) is None


@patch("app.services.crawl_payload.upload_notice_html")
def test_build_notice_payload_skips_placeholder_title(mock_upload):
    """placeholder 제목이면 None."""
    mock_upload.return_value = "https://storage/url"
    college_id = uuid.uuid4()
    assert build_notice_payload(
        college_id,
        {},
        "https://u",
        "제목 없음",
        None,
        "<p>x</p>",
        [],
        [],
        None,
        None,
    ) is None
    assert build_notice_payload(
        college_id,
        {},
        "https://u",
        "(본문 영역을 찾을 수 없습니다)",
        None,
        "<p>x</p>",
        [],
        [],
        None,
        None,
    ) is None


@patch("app.services.crawl_payload.upload_notice_html")
def test_build_notice_payload_skips_html_too_large(mock_upload):
    """HTML 크기 초과 시 None (MAX_HTML_BYTES)."""
    from app.services.crawl_payload import MAX_HTML_BYTES

    college_id = uuid.uuid4()
    large = "x" * (MAX_HTML_BYTES + 1)
    assert build_notice_payload(
        college_id, {}, "https://u", "Title", None, large, [], [], None, None
    ) is None
    mock_upload.assert_not_called()


@patch("app.services.crawl_payload.upload_notice_html")
def test_build_notice_payload_returns_payload(mock_upload):
    """정상 입력 시 payload dict 반환 및 upload_notice_html 호출."""
    mock_upload.return_value = "https://storage/content-url"
    college_id = uuid.uuid4()
    payload = build_notice_payload(
        college_id,
        {"no": "ext-1"},
        "https://example.com/view?articleNo=1",
        "공지 제목",
        "2024.01.15",
        "<p>본문</p>",
        [],
        [],
        body_text_for_hash=None,
        external_id=None,
    )
    assert payload is not None
    assert payload["college_id"] == college_id
    assert payload["external_id"] == "ext-1"
    assert payload["title"] == "공지 제목"
    assert payload["url"] == "https://example.com/view?articleNo=1"
    assert payload["content_url"] == "https://storage/content-url"
    assert payload["content_hash"]
    assert payload["published_at"] is not None
    assert payload["published_at"].year == 2024
    mock_upload.assert_called_once()
