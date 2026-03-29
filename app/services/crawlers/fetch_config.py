"""크롤러 모듈별 HTTP fetch 옵션 선언. 하드코딩 timeout/encoding 반복 축소."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ("CrawlerFetchConfig", "BUSINESS_SITE_FETCH")


@dataclass(frozen=True, slots=True)
class CrawlerFetchConfig:
    list_timeout_seconds: float = 10.0
    detail_timeout_seconds: float = 10.0
    list_encoding: str = "utf-8"
    detail_encoding: str = "utf-8"
    list_request_meta: dict[str, Any] | None = None
    detail_request_meta: dict[str, Any] | None = None


BUSINESS_SITE_FETCH = CrawlerFetchConfig(list_encoding="cp949", detail_encoding="cp949")
