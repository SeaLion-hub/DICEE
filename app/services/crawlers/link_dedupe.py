"""크롤러 목록 링크 URL 기준 중복 제거."""

from __future__ import annotations

from typing import Any


def dedupe_link_dicts_by_url(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 url은 첫 항목만 유지. url이 비어 있으면 스킵."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in links:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out
