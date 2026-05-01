"""yonsei_engineering 상세 HTML 파서 단위 테스트(I/O 없음)."""

from pathlib import Path

import pytest
from app.services.crawlers.base import ParserStructureError
from app.services.crawlers.yonsei_engineering import parse_yonsei_engineering_precise_from_html

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "yonsei_engineering_detail_min.html"


@pytest.fixture
def engineering_detail_html() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def test_parse_yonsei_engineering_from_fixture_extracts_title_date_body(engineering_detail_html: str) -> None:
    url = "https://engineering.yonsei.ac.kr/engineering/board/notice.do?mode=view"
    result = parse_yonsei_engineering_precise_from_html(engineering_detail_html, url)

    assert result.title == "Fixture 공지 제목"
    assert result.date_str == "2024-03-15"
    assert "본문 첫 줄" in (result.html_content or "")
    assert "https://engineering.yonsei.ac.kr/engine/data/file.png" in str(result.images)
    assert "report.pdf" in result.attachments


def test_parse_yonsei_engineering_missing_body_anchor_raises_parser_error() -> None:
    html = "<html><body><h3>Only Title</h3><p>2099-12-31</p></body></html>"
    with pytest.raises(ParserStructureError):
        parse_yonsei_engineering_precise_from_html(html, "https://example.com/x")
