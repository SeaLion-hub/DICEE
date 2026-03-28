"""Crawler contracts and scaffolding for function-based and class-based plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from app.core.crawl_http import fetch_html, fetch_html_detail_cached


class _LinkItemOptional(TypedDict, total=False):
    no: str
    title_hint: str


class LinkItem(_LinkItemOptional):
    url: str


@dataclass(slots=True)
class ScrapeResult:
    """Crawler detail result shared by all college crawler modules."""

    title: str | None
    date_str: str
    html_content: str | None
    images: list[dict[str, Any]]
    attachments: list[str]


class CrawlerStrategy(Protocol):
    """Sync crawler contract used by the crawl pipeline registry."""

    def get_links(self, list_url: str) -> list[LinkItem]: ...

    def scrape_detail(self, url: str) -> ScrapeResult: ...


class BaseCrawler(ABC):
    """
    Class-based crawler scaffold.

    New crawler modules only need:
    - `start_urls`
    - `parse_links(html, list_url)`
    - `parse_detail(html, detail_url)`
    """

    college_code: str = ""
    display_name: str = ""
    start_urls: tuple[str, ...] = ()

    list_timeout_seconds: float = 10.0
    detail_timeout_seconds: float = 10.0
    list_encoding: str = "utf-8"
    detail_encoding: str = "utf-8"
    list_request_meta: dict[str, Any] | None = None
    detail_request_meta: dict[str, Any] | None = None

    def default_list_url(self) -> str:
        return self.start_urls[0] if self.start_urls else ""

    def get_links(self, list_url: str) -> list[LinkItem]:
        target_url = (list_url or "").strip() or self.default_list_url()
        if not target_url:
            raise ValueError("list_url is required for crawler execution")
        html = fetch_html(
            target_url,
            timeout=self.list_timeout_seconds,
            encoding=self.list_encoding,
            request_meta=self.list_request_meta,
        )
        return self.parse_links(html, target_url)

    def scrape_detail(self, url: str) -> ScrapeResult:
        html = fetch_html_detail_cached(
            url,
            timeout=self.detail_timeout_seconds,
            encoding=self.detail_encoding,
            request_meta=self.detail_request_meta,
        )
        return self.parse_detail(html, url)

    @abstractmethod
    def parse_links(self, html: str, list_url: str) -> list[LinkItem]: ...

    @abstractmethod
    def parse_detail(self, html: str, url: str) -> ScrapeResult: ...

    def to_crawler_spec(
        self,
        *,
        get_links_name: str = "get_notice_links",
        scrape_detail_name: str = "scrape_detail",
    ):
        """Build a `CrawlerModuleSpec` for module-level registry wiring."""
        from app.core.crawler_config import CrawlerModuleSpec

        list_url = self.default_list_url()
        if not list_url:
            raise ValueError("BaseCrawler.start_urls must contain at least one URL")
        return CrawlerModuleSpec(
            college_code=self.college_code,
            display_name=self.display_name,
            list_url=list_url,
            get_links=get_links_name,
            scrape_detail=scrape_detail_name,
        )

    def legacy_exports(self) -> tuple[Callable[[str], list[LinkItem]], Callable[[str], ScrapeResult]]:
        """Expose function callables compatible with the current crawler registry."""
        return (self.get_links, self.scrape_detail)


class FunctionCrawlerAdapter:
    """Wrap function-based crawlers with object-style strategy methods."""

    def __init__(
        self,
        *,
        get_links_fn: Callable[[str], list[LinkItem]],
        scrape_detail_fn: Callable[[str], ScrapeResult],
    ) -> None:
        self._get_links_fn = get_links_fn
        self._scrape_detail_fn = scrape_detail_fn

    def get_links(self, list_url: str) -> list[LinkItem]:
        return self._get_links_fn(list_url)

    def scrape_detail(self, url: str) -> ScrapeResult:
        return self._scrape_detail_fn(url)
