"""yonsei_chemistry 목록·상세 파서 단위 테스트(I/O는 fetch mock)."""

from pathlib import Path

import pytest
from app.services.crawlers import yonsei_chemistry as chem
from app.services.crawlers.base import ParserStructureError

_LIST_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "yonsei_chemistry_list_min.html"
_DETAIL_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "yonsei_chemistry_detail_min.html"


def test_get_chemistry_links_from_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _LIST_FIXTURE.read_text(encoding="utf-8")
    base = "https://chemyonsei.kr/board/notice"

    def _fake_fetch(_url: str, timeout: float = 10) -> str:
        return html

    monkeypatch.setattr(chem, "fetch_html", _fake_fetch)
    links = chem.get_chemistry_links(base)
    assert len(links) == 1
    assert links[0]["no"] == "12"
    assert links[0]["title_hint"] == "화학 세미나 안내"
    assert links[0]["url"] == "https://chemyonsei.kr/board/notice/99"


def test_scrape_chemistry_detail_from_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _DETAIL_FIXTURE.read_text(encoding="utf-8")
    url = "https://chemyonsei.kr/board/notice/99"

    def _fake_detail(_u: str, timeout: float = 10) -> str:
        assert _u == url
        return html

    monkeypatch.setattr(chem, "fetch_html_detail_cached", _fake_detail)
    result = chem.scrape_chemistry_detail(url)
    assert result.title == "화학과 상세 제목"
    assert result.date_str in {"2024-06-01", "2024.06.01"}
    assert "상세 본문 단락" in (result.html_content or "")
    assert any("chem.png" in (img.get("data") or "") for img in result.images)


def test_scrape_chemistry_missing_content_selector_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://chemyonsei.kr/board/notice/99"
    html = "<html><body><h3 class='nxb-view__header-title'>Title</h3><time>2024-06-01</time></body></html>"

    monkeypatch.setattr(chem, "fetch_html_detail_cached", lambda *_args, **_kwargs: html)

    with pytest.raises(ParserStructureError):
        chem.scrape_chemistry_detail(url)
