"""BoardView* ID 계열(경영·IGEE·언더우드 등) 공통 DOM 조회."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag


def board_view_title_from_soup(soup: BeautifulSoup) -> str:
    """BoardViewTitle 우선, 없으면 첫 h2/h3."""
    t_elem = soup.find(id="BoardViewTitle")
    if t_elem and isinstance(t_elem, Tag):
        return t_elem.get_text(strip=True)
    h = soup.find(["h2", "h3"])
    if isinstance(h, Tag):
        return h.get_text(strip=True)
    return ""
