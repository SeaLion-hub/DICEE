"""Scrapy-style item pipeline primitives for crawl payload processing and persistence."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import CRAWL_DROP_TOTAL, DROP_REASON_DUPLICATE, DROP_REASON_PAYLOAD_BUILD_NONE, increment
from app.domain.contracts.crawl_contracts import CrawlLogContext, LinkItem, NoticeDraft
from app.services.crawl_payload import _external_id_from_url, build_notice_payload
from app.services.crawlers.base import ScrapeResult


class _SeenSet(Protocol):
    def add(self, x: str) -> None: ...

    def __contains__(self, x: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class RawNoticeItem:
    college_id: uuid.UUID
    post: LinkItem
    detail_url: str
    data: ScrapeResult
    external_id: str | None = None


class ItemPipelineStage(Protocol):
    def process(
        self, item: RawNoticeItem | NoticeDraft, ctx: CrawlLogContext
    ) -> RawNoticeItem | NoticeDraft | None: ...


class ExternalIdResolveStage:
    """Resolve item external_id from link metadata or URL query/path."""

    def process(self, item: RawNoticeItem | NoticeDraft, ctx: CrawlLogContext) -> RawNoticeItem | NoticeDraft | None:
        if isinstance(item, NoticeDraft):
            return item
        if item.external_id:
            return item
        resolved = item.post.get("no") or _external_id_from_url(item.detail_url) or None
        if not resolved:
            return None
        return RawNoticeItem(
            college_id=item.college_id,
            post=item.post,
            detail_url=item.detail_url,
            data=item.data,
            external_id=resolved,
        )


class DeduplicationStage:
    """Drop duplicate external_id items before payload build."""

    def __init__(self, seen: _SeenSet) -> None:
        self._seen = seen

    def process(self, item: RawNoticeItem | NoticeDraft, ctx: CrawlLogContext) -> RawNoticeItem | NoticeDraft | None:
        if isinstance(item, NoticeDraft):
            return item
        if not item.external_id:
            return item
        if item.external_id in self._seen:
            increment(CRAWL_DROP_TOTAL, 1, labels={"reason": DROP_REASON_DUPLICATE})
            return None
        return item


class NoticeDraftBuildStage:
    """Convert raw crawler output to NoticeDraft and register seen-id on success."""

    def __init__(self, seen: _SeenSet) -> None:
        self._seen = seen

    def process(self, item: RawNoticeItem | NoticeDraft, ctx: CrawlLogContext) -> RawNoticeItem | NoticeDraft | None:
        if isinstance(item, NoticeDraft):
            return item
        data = item.data
        html_content = data.html_content
        body_text_for_hash = (
            BeautifulSoup(html_content, "html.parser").get_text(separator="\n", strip=True) if html_content else ""
        )
        payload = build_notice_payload(
            item.college_id,
            item.post,
            item.detail_url,
            data.title or "",
            data.date_str,
            html_content,
            data.images,
            data.attachments,
            body_text_for_hash=body_text_for_hash or None,
            external_id=item.external_id,
            ctx=ctx,
        )
        if payload is None:
            increment(CRAWL_DROP_TOTAL, 1, labels={"reason": DROP_REASON_PAYLOAD_BUILD_NONE})
            return None
        if item.external_id:
            self._seen.add(item.external_id)
        return payload


class ItemPipelineChain:
    """Sequential pipeline execution: `item -> stage1 -> stage2 -> ...`."""

    def __init__(self, stages: Sequence[ItemPipelineStage]) -> None:
        self._stages = list(stages)

    def process(self, item: RawNoticeItem, ctx: CrawlLogContext) -> NoticeDraft | None:
        current: RawNoticeItem | NoticeDraft | None = item
        for stage in self._stages:
            if current is None:
                return None
            current = stage.process(current, ctx)
        return current if isinstance(current, NoticeDraft) else None


class DefaultNoticeItemPipeline:
    """Default pipeline: resolve external_id -> de-dup -> build NoticeDraft."""

    def __init__(self, seen: _SeenSet) -> None:
        self._chain = ItemPipelineChain(
            [
                ExternalIdResolveStage(),
                DeduplicationStage(seen),
                NoticeDraftBuildStage(seen),
            ]
        )

    def process(self, item: RawNoticeItem, ctx: CrawlLogContext) -> NoticeDraft | None:
        return self._chain.process(item, ctx)


class NoticeBulkUpsertPipeline:
    """Persistence pipeline stage for `NoticeDraft[] -> DB upsert` conversion."""

    def __init__(self, upsert_fn: Callable[[Session, list[NoticeDraft]], list[uuid.UUID]]) -> None:
        self._upsert_fn = upsert_fn

    def process(self, session: Session, drafts: list[NoticeDraft]) -> list[uuid.UUID]:
        if not drafts:
            return []
        ids = self._upsert_fn(session, drafts)
        if settings.notice_preprocess_after_bulk_upsert and ids:
            from app.services.notice_preprocess.pipeline import apply_batch_preprocess_sync

            apply_batch_preprocess_sync(session, ids)
        return ids
