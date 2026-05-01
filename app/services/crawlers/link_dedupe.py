"""크롤러 목록 링크 URL 기준 중복 제거."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonicalize_link_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True)
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            query,
            "",
        )
    )


def dedupe_link_dicts_by_url(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 url은 첫 항목만 유지. url이 비어 있으면 스킵."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in links:
        url = (item.get("url") or "").strip()
        key = canonicalize_link_url(url)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
