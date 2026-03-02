"""Sync crawl pipeline: adapter, finalize chunk, run pipeline, crawl_college_sync."""

import logging
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Protocol, cast

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crawler_config import get_crawler
from app.domain.contracts.crawl_contracts import (
    EVENT_LIST_FETCH_FAILED,
    EVENT_PARSE_FAILED,
    EVENT_UPSERT_FAILED,
    CrawlLogContext,
    CrawlPhase,
    LinkItem,
    NoticeDraft,
)
from app.repositories.college_repository import get_by_external_id_sync as get_college_by_external_id_sync
from app.repositories.crawl_run_repository import update_crawl_run_checkpoint_sync
from app.repositories.notice_repository import upsert_notices_bulk_sync

from .collect_sync import _collect_payloads_sync
from .item_pipeline import NoticeBulkUpsertPipeline
from .runtime import (
    CrawlRuntimeConfig,
    _cap_links_for_run,
    _init_seen_set_sync,
    _load_crawl_runtime_config,
    _RedisSeenSet,
    _resolve_module_and_list_url,
    _SeenSet,
)

logger = logging.getLogger(__name__)


class _SyncCrawlAdapter(Protocol):
    def collect_payloads(
        self,
        *,
        links: list[LinkItem],
        college_id: uuid.UUID,
        scrape_fn: Callable,
        seen: _SeenSet,
        cfg: CrawlRuntimeConfig,
        ctx: CrawlLogContext,
    ) -> Iterator[NoticeDraft]: ...

    def upsert_chunk(self, session: Session, chunk: list[NoticeDraft]) -> list[uuid.UUID]: ...


class _DefaultSyncCrawlAdapter:
    def __init__(self, upsert_pipeline: NoticeBulkUpsertPipeline | None = None) -> None:
        self._upsert_pipeline = upsert_pipeline or NoticeBulkUpsertPipeline(upsert_notices_bulk_sync)

    def collect_payloads(
        self,
        *,
        links: list[LinkItem],
        college_id: uuid.UUID,
        scrape_fn: Callable,
        seen: _SeenSet,
        cfg: CrawlRuntimeConfig,
        ctx: CrawlLogContext,
    ) -> Iterator[NoticeDraft]:
        return _collect_payloads_sync(
            links,
            college_id,
            scrape_fn,
            cfg.polite_delay_seconds,
            seen=seen,
            max_workers=cfg.collect_sync_max_workers,
            in_flight_limit=cfg.collect_in_flight_limit,
            ctx=ctx,
        )

    def upsert_chunk(self, session: Session, chunk: list[NoticeDraft]) -> list[uuid.UUID]:
        return self._upsert_pipeline.process(session, chunk)


def _finalize_chunk_sync(
    session: Session,
    adapter: _SyncCrawlAdapter,
    chunk: list[NoticeDraft],
    *,
    on_chunk_processed: Callable[[list[uuid.UUID]], None] | None,
    notice_ids_to_process: list[uuid.UUID],
    run_id: uuid.UUID | None = None,
    total_processed_before_chunk: int = 0,
) -> int:
    ids = adapter.upsert_chunk(session, chunk)
    n = len(ids)
    chunk.clear()
    if run_id is not None:
        update_crawl_run_checkpoint_sync(
            session,
            run_id,
            processed_count=total_processed_before_chunk + n,
            checkpointed_at=datetime.now(UTC),
        )
    if on_chunk_processed is not None:
        session.commit()
        session.expunge_all()
        on_chunk_processed(ids)
    else:
        notice_ids_to_process.extend(ids)
    return n


def _finalize_chunk_sync_with_phase_log(
    session: Session,
    adapter: _SyncCrawlAdapter,
    chunk: list[NoticeDraft],
    ctx: CrawlLogContext,
    *,
    on_chunk_processed: Callable[[list[uuid.UUID]], None] | None,
    notice_ids_to_process: list[uuid.UUID],
    run_id: uuid.UUID | None = None,
    total_processed_before_chunk: int = 0,
) -> int:
    import time

    chunk_size = len(chunk)
    t0 = time.perf_counter()
    try:
        n = _finalize_chunk_sync(
            session,
            adapter,
            chunk,
            on_chunk_processed=on_chunk_processed,
            notice_ids_to_process=notice_ids_to_process,
            run_id=run_id,
            total_processed_before_chunk=total_processed_before_chunk,
        )
        elapsed = time.perf_counter() - t0
        logger.debug(
            "crawl upsert chunk college_code=%s chunk_size=%d elapsed_sec=%.3f",
            ctx.college_code,
            chunk_size,
            elapsed,
            extra={**ctx.extra_for_log(), "chunk_size": chunk_size, "elapsed_sec": round(elapsed, 3)},
        )
        return n
    except Exception as e:
        from app.core.logging_context import set_request_context

        set_request_context(event_code=EVENT_UPSERT_FAILED)
        log_extra = {
            **ctx.extra_for_log(),
            "phase": CrawlPhase.UPSERT.value,
            "event_code": EVENT_UPSERT_FAILED,
            "chunk_size": chunk_size,
        }
        logger.warning("crawl upsert failed: %s", e, exc_info=True, extra=log_extra)
        raise


def _run_crawl_pipeline_sync(
    session: Session,
    *,
    college_code: str,
    college_id: uuid.UUID,
    list_url: str,
    get_links_fn: Callable,
    scrape_fn: Callable,
    run_id: uuid.UUID | None,
    task_id: str | None = None,
    on_chunk_processed: Callable[[list[uuid.UUID]], None] | None,
    cfg: CrawlRuntimeConfig,
    adapter: _SyncCrawlAdapter,
) -> tuple[int, list[uuid.UUID]]:
    try:
        links_raw = get_links_fn(list_url)
    except Exception as e:
        from app.core.logging_context import set_request_context

        set_request_context(event_code=EVENT_LIST_FETCH_FAILED)
        log_extra = {
            "college_code": college_code,
            "run_id": str(run_id) if run_id else "",
            "task_id": task_id or "",
            "phase": CrawlPhase.LIST.value,
            "event_code": EVENT_LIST_FETCH_FAILED,
        }
        logger.warning("crawl list fetch failed: %s", e, exc_info=True, extra=log_extra)
        raise
    links = _cap_links_for_run(cast(list[LinkItem], links_raw), college_code, cfg.max_links_per_run)
    total_links = len(links)
    if not links:
        logger.info(
            "crawl finished college_code=%s total_links=0 upserted=0",
            college_code,
        )
        return (0, [])

    ctx = CrawlLogContext(college_code=college_code, run_id=run_id, task_id=task_id)
    raw_redis = (settings.redis.redis_url or "").strip()
    crawl_seen_required = settings.redis.redis_crawl_seen_required
    seen = _init_seen_set_sync(
        run_id=run_id,
        redis_url=raw_redis,
        redis_required=crawl_seen_required,
        seen_max_size=cfg.crawl_seen_max_size,
    )
    notice_ids_to_process: list[uuid.UUID] = []
    total_upserted = 0
    chunk: list[NoticeDraft] = []
    try:
        try:
            for payload in adapter.collect_payloads(
                links=links,
                college_id=college_id,
                scrape_fn=scrape_fn,
                seen=seen,
                cfg=cfg,
                ctx=ctx,
            ):
                chunk.append(payload)
                if len(chunk) >= cfg.upsert_chunk_size:
                    total_upserted += _finalize_chunk_sync_with_phase_log(
                        session,
                        adapter,
                        chunk,
                        ctx,
                        on_chunk_processed=on_chunk_processed,
                        notice_ids_to_process=notice_ids_to_process,
                        run_id=run_id,
                        total_processed_before_chunk=total_upserted,
                    )
            if chunk:
                total_upserted += _finalize_chunk_sync_with_phase_log(
                    session,
                    adapter,
                    chunk,
                    ctx,
                    on_chunk_processed=on_chunk_processed,
                    notice_ids_to_process=notice_ids_to_process,
                    run_id=run_id,
                    total_processed_before_chunk=total_upserted,
                )
        except Exception as e:
            from app.core.logging_context import set_request_context

            set_request_context(event_code=EVENT_PARSE_FAILED)
            log_extra = {
                **ctx.extra_for_log(),
                "phase": CrawlPhase.SCRAPE.value,
                "event_code": EVENT_PARSE_FAILED,
            }
            logger.warning("crawl scrape/parse failed: %s", e, exc_info=True, extra=log_extra)
            raise
    finally:
        if isinstance(seen, _RedisSeenSet):
            seen.close()

    logger.info(
        "crawl finished college_code=%s total_links=%d upserted=%d",
        college_code,
        total_links,
        total_upserted,
    )
    if on_chunk_processed is not None:
        return (total_upserted, [])
    return (total_upserted, notice_ids_to_process)


def crawl_college_sync(
    session: Session,
    college_code: str,
    *,
    run_id: uuid.UUID | None = None,
    task_id: str | None = None,
    on_chunk_processed: Callable[[list[uuid.UUID]], None] | None = None,
) -> tuple[int, list[uuid.UUID]]:
    """
    단과대 1개 크롤 (동기, Celery 워커 전용). 동기 DB 세션·Repository 사용.
    get_*_links / (1초 sleep) / scrape_*_detail → upsert_notice_sync.
    """
    college = get_college_by_external_id_sync(session, college_code)
    if not college:
        raise ValueError(f"College not found: {college_code}")

    module_name, list_url = _resolve_module_and_list_url(college_code)
    get_links_fn, scrape_fn = get_crawler(module_name)
    cfg = _load_crawl_runtime_config()
    return _run_crawl_pipeline_sync(
        session,
        college_code=college_code,
        college_id=college.id,
        list_url=list_url,
        get_links_fn=get_links_fn,
        scrape_fn=scrape_fn,
        run_id=run_id,
        task_id=task_id,
        on_chunk_processed=on_chunk_processed,
        cfg=cfg,
        adapter=_DefaultSyncCrawlAdapter(),
    )
