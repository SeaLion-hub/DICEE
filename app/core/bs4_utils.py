"""BeautifulSoup 노드 타입 좁히기 헬퍼 (mypy·런타임 안전)."""

from __future__ import annotations

from bs4 import Tag


def as_tag(node: object) -> Tag | None:
    """PageElement 등이 넘어와도 Tag일 때만 반환한다."""
    return node if isinstance(node, Tag) else None
