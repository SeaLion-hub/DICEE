"""NoticePreviewService flattening behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.notice_preview_service import NoticePreviewService


def _notice() -> MagicMock:
    notice = MagicMock()
    notice.title = "Preview Title"
    notice.published_at = datetime(2026, 4, 1, 12, 30, 45, 123456, tzinfo=UTC)
    notice.url = "https://example.com/notice"
    notice.notice_content = MagicMock()
    notice.notice_content.content_url = " https://cdn.example/content.html "
    notice.images = [
        {"url": "https://cdn.example/image-a.png"},
        {"src": "https://cdn.example/image-b.png"},
        "bad",
        {"url": "   "},
    ]
    notice.attachments = [
        {"name": "a.pdf"},
        {"filename": "b.hwp"},
        {"url": "https://cdn.example/c"},
        "bad",
    ]
    notice.eligibility = ["  3학년  ", "", None]
    notice.dates = [
        {"label": "접수", "starts_at": "2026-04-01", "ends_at": "2026-04-10"},
        {"kind": "interview", "start_date_raw": "4월 중"},
        {"label": "발표", "date_raw": "5월 초"},
        "bad",
    ]
    notice.ai_extracted_json = {
        "main_categories": ["장학/지원", "장학/지원"],
        "taxonomy_mappings": [
            {"main_category": "장학/지원", "sub_categories": ["교내장학", "교내장학", "외부장학"]},
            {"main_category": "취업/진로", "sub_categories": ["인턴십"]},
            "bad",
        ],
    }
    return notice


@pytest.mark.asyncio
async def test_get_engineering_preview_flattens_notice_fields() -> None:
    session = AsyncMock()

    with patch(
        "app.services.notice_preview_service.list_recent_notices_for_college_preview",
        new_callable=AsyncMock,
    ) as list_recent:
        list_recent.return_value = [_notice()]
        rows = await NoticePreviewService().get_engineering_preview(session, limit=3)

    list_recent.assert_awaited_once_with(session, college_external_id="engineering", limit=3)
    assert len(rows) == 1
    row = rows[0]
    assert row.title == "Preview Title"
    assert row.published_at == "2026-04-01T12:30:45Z"
    assert row.url == "https://example.com/notice"
    assert row.content_url == "https://cdn.example/content.html"
    assert row.image_urls == ["https://cdn.example/image-a.png", "https://cdn.example/image-b.png"]
    assert row.attachment_names == ["a.pdf", "b.hwp", "https://cdn.example/c"]
    assert row.eligibility == ["3학년"]
    assert row.dates == ["접수: 2026-04-01 ~ 2026-04-10", "interview: 4월 중", "발표: 5월 초"]
    assert row.main_categories == ["장학/지원", "취업/진로"]
    assert row.sub_categories == ["교내장학", "외부장학", "인턴십"]


def test_extract_image_urls_accepts_url_or_src_and_skips_invalid_items() -> None:
    assert NoticePreviewService._extract_image_urls(
        [
            {"url": "https://example.com/a.png"},
            {"src": "https://example.com/b.png"},
            {"url": " "},
            "bad",
        ]
    ) == ["https://example.com/a.png", "https://example.com/b.png"]


def test_extract_attachment_names_falls_back_name_filename_url() -> None:
    assert NoticePreviewService._extract_attachment_names(
        [
            {"name": "a.pdf"},
            {"filename": "b.hwp"},
            {"url": "https://example.com/c"},
            {"name": " "},
            "bad",
        ]
    ) == ["a.pdf", "b.hwp", "https://example.com/c"]


def test_extract_taxonomy_combines_rows_and_ai_json_with_dedupe() -> None:
    row = MagicMock()
    row.main_category = "장학/지원"
    row.sub_category = "교내장학"

    main, sub = NoticePreviewService._extract_taxonomy(
        taxonomy_mappings=[row],
        ai_extracted_json={
            "main_categories": ["장학/지원", "취업/진로"],
            "taxonomy_mappings": [
                {"main_category": "장학/지원", "sub_categories": ["교내장학", "외부장학"]},
                {"main_category": "취업/진로", "sub_categories": ["인턴십"]},
            ],
        },
    )

    assert main == ["장학/지원", "취업/진로"]
    assert sub == ["교내장학", "외부장학", "인턴십"]


@pytest.mark.asyncio
async def test_get_engineering_preview_handles_empty_optional_fields() -> None:
    notice = MagicMock()
    notice.title = None
    notice.published_at = None
    notice.url = None
    notice.notice_content = None
    notice.images = None
    notice.attachments = None
    notice.eligibility = None
    notice.dates = None
    notice.ai_extracted_json = None

    with patch(
        "app.services.notice_preview_service.list_recent_notices_for_college_preview",
        new_callable=AsyncMock,
        return_value=[notice],
    ):
        rows = await NoticePreviewService().get_engineering_preview(AsyncMock())
    assert rows[0].title == ""
    assert rows[0].published_at == ""
    assert rows[0].url == ""
    assert rows[0].content_url == ""
    assert rows[0].image_urls == []
    assert rows[0].attachment_names == []
    assert rows[0].eligibility == []
    assert rows[0].dates == []
    assert rows[0].main_categories == []
    assert rows[0].sub_categories == []
