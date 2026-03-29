"""크롤 수집 결과를 정규화 패킷으로 매핑 (Celery·테스트 경계)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Iterator

from app.domain.contracts.crawl_contracts import NoticeDraft
from app.domain.contracts.crawl_runner_contracts import (
    CrawlRunnerCheckpoint,
    CrawlRunnerFailure,
    CrawlRunnerPacket,
    NoticeRunnerDocument,
)


def notice_draft_to_runner_document(draft: NoticeDraft) -> NoticeRunnerDocument:
    return NoticeRunnerDocument(
        college_id=draft.college_id,
        external_id=draft.external_id,
        title=draft.title,
        url=draft.url,
        content_url=draft.content_url,
        images=draft.images,
        attachments=list(draft.attachments or []),
        content_hash=draft.content_hash,
        published_at=draft.published_at,
    )


def iter_packets_from_drafts(drafts: Iterable[NoticeDraft]) -> Iterator[NoticeRunnerDocument]:
    for d in drafts:
        yield notice_draft_to_runner_document(d)


def list_fetch_failure_packet(message: str, *, event_code: str | None = None) -> CrawlRunnerFailure:
    return CrawlRunnerFailure(phase="list", message=message, detail_url=None, event_code=event_code)


def scrape_failure_packet(
    message: str,
    *,
    detail_url: str | None = None,
    event_code: str | None = None,
) -> CrawlRunnerFailure:
    return CrawlRunnerFailure(phase="scrape", message=message, detail_url=detail_url, event_code=event_code)


def checkpoint_packet(processed_count: int, pointer: dict | None = None) -> CrawlRunnerCheckpoint:
    return CrawlRunnerCheckpoint(processed_count=processed_count, pointer=dict(pointer or {}))


def run_list_then_collect_packets(
    *,
    list_url: str,
    get_links_fn: Callable[[str], list],
    collect_drafts_fn: Callable[[list, uuid.UUID], Iterable[NoticeDraft]],
    college_id: uuid.UUID,
) -> Iterator[CrawlRunnerPacket]:
    """
    리스트 실패 시 CrawlRunnerFailure 한 건 yield 후 종료.
    성공 시 수집된 NoticeDraft를 NoticeRunnerDocument로 변환하여 yield.
    """
    try:
        links_raw = get_links_fn(list_url)
    except Exception as e:
        yield list_fetch_failure_packet(str(e), event_code="CRAWL_LIST_FETCH_FAILED")
        return
    yield from iter_packets_from_drafts(collect_drafts_fn(links_raw, college_id))
