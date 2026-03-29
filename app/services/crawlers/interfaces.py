"""Capability 기반 크롤러 프로토콜. BaseCrawler는 parse_links/parse_detail로 사실상 Load+Poll."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.domain.contracts.crawl_contracts import LinkItem
from app.services.crawlers.base import BaseCrawler, ScrapeResult


@runtime_checkable
class LoadCrawler(Protocol):
    """전량/초기 로드: 시작 URL에서 목록을 가져온다."""

    start_urls: tuple[str, ...]

    def get_links(self, list_url: str) -> list[LinkItem]: ...


@runtime_checkable
class PollCrawler(Protocol):
    """증분 폴링: 동일 목록 소스를 주기적으로 다시 읽는다 (시그니처는 Load와 동일하게 둠)."""

    def get_links(self, list_url: str) -> list[LinkItem]: ...


@runtime_checkable
class CheckpointedCrawler(Protocol):
    """체크포인트 지원 (선택). 구현체가 resume/pointer 메서드를 추가하면 된다."""

    def load_checkpoint_pointer(self) -> dict[str, Any] | None:
        """저장된 포인터가 없으면 None."""
        ...


def crawler_capabilities(obj: object) -> dict[str, bool]:
    """객체가 어떤 capability를 만족하는지 런타임 검사 (로깅·검증용)."""
    return {
        "load": isinstance(obj, LoadCrawler),
        "poll": isinstance(obj, PollCrawler),
        "checkpointed": isinstance(obj, CheckpointedCrawler),
    }


def scrape_result_from_base(crawler: BaseCrawler, url: str) -> ScrapeResult:
    """BaseCrawler 인스턴스에서 상세 스크랩 (공통 진입점)."""
    return crawler.scrape_detail(url)
