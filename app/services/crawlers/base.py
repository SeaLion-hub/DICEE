"""
크롤러 공통 인터페이스(Strategy Pattern).
새 단과대 추가 시 이 프로토콜만 구현하면 되도록 O(1) 유지보수.
"""

from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

import httpx


# 링크 항목: url 필수, no·title_hint 선택. 크롤러별로 추가 키 가능.
class _LinkItemOptional(TypedDict, total=False):
    no: str
    title_hint: str


class LinkItem(_LinkItemOptional):
    url: str


@dataclass(slots=True)
class ScrapeResult:
    """상세 스크래핑 결과. 내부 모듈 간 전달용. dataclass(slots=True)로 메모리·속도 우선."""

    title: str | None
    date_str: str
    html_content: str | None
    images: list[dict[str, Any]]
    attachments: list[str]


class CrawlerStrategy(Protocol):
    """동기 크롤러 전략. get_links + scrape_detail 시그니처 통일."""

    def get_links(self, list_url: str) -> list[LinkItem]:
        """목록 URL에서 공지 링크 목록 반환. 최소 키: url."""
        ...

    def scrape_detail(self, url: str) -> ScrapeResult:
        """상세 URL에서 (title, date_str, html_content, images, attachments) 반환."""
        ...


class AsyncCrawlerStrategy(Protocol):
    """비동기 크롤러 전략. get_links_async + scrape_detail_async 시그니처 통일."""

    async def get_links_async(
        self, client: httpx.AsyncClient, list_url: str
    ) -> list[LinkItem]:
        """목록 URL에서 공지 링크 목록 반환(비동기)."""
        ...

    async def scrape_detail_async(
        self, client: httpx.AsyncClient, url: str
    ) -> ScrapeResult:
        """상세 URL에서 (title, date_str, html_content, images, attachments) 반환(비동기)."""
        ...
