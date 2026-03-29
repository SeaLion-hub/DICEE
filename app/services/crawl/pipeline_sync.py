"""
Sync crawl pipeline: adapter, finalize chunk, run pipeline, crawl_college_sync.

Chunk 경계에서 commit+expunge 후 콜백(Crawlee handler 결과 배치 플러시와 동일한 역할).
"""

import logging
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Protocol, cast

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import IngestionBatchStatus
from app.core.crawler_config import get_crawler
from app.core.metrics import CRAWL_PIPELINE_PEAK_PENDING_DRAFTS, set_gauge
from app.domain.contracts.crawl_contracts import (
    EVENT_LIST_FETCH_FAILED,
    EVENT_PARSE_FAILED,
    EVENT_UPSERT_FAILED,
    CrawlLogContext,
    CrawlPhase,
    LinkItem,
    NoticeDraft,
)
from app.domain.contracts.notice_draft_serde import notice_draft_to_payload
from app.models.ingestion_batch import IngestionBatch
from app.repositories.crawl_run_repository import update_crawl_run_checkpoint_sync
from app.repositories.ingestion_attempt_repository import (
    add_ingestion_scheduled_docs_sync,
    increment_attempt_total_batches_sync,
)
from app.repositories.notice_repository import upsert_notices_bulk_sync

from .collect_sync import _collect_payloads_sync
from .item_pipeline import NoticeBulkUpsertPipeline
from .runtime import (
    CrawlRuntimeConfig,
    _cap_links_for_run,
    _init_seen_set_sync,
    _load_crawl_runtime_config,
    _RedisSeenSet,
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


class DeferredBatchCrawlAdapter(_DefaultSyncCrawlAdapter):
    """수집 청크를 ingestion_batches에 저장 후 비동기 process_notice_ingestion_batch_task에서 upsert."""

    def __init__(
        self,
        *,
        attempt_id: uuid.UUID,
        college_code: str,
        sequence_counter: list[int],
        upsert_pipeline: NoticeBulkUpsertPipeline | None = None,
    ) -> None:
        super().__init__(upsert_pipeline=upsert_pipeline)
        self._attempt_id = attempt_id
        self._college_code = college_code
        self._sequence_counter = sequence_counter

    def upsert_chunk(self, session: Session, chunk: list[NoticeDraft]) -> list[uuid.UUID]:
        if not chunk:
            return []
        self._sequence_counter[0] += 1
        seq = self._sequence_counter[0]
        payloads = [notice_draft_to_payload(d) for d in chunk]
        batch = IngestionBatch(
            attempt_id=self._attempt_id,
            sequence=seq,
            status=IngestionBatchStatus.PENDING.value,
            drafts_payload=payloads,
            created_at=datetime.now(UTC),
            processed_at=None,
        )
        session.add(batch)
        session.flush()
        increment_attempt_total_batches_sync(session, self._attempt_id)
        add_ingestion_scheduled_docs_sync(session, self._attempt_id, len(chunk))
        from app.services.tasks import process_notice_ingestion_batch_task

        process_notice_ingestion_batch_task.delay(str(batch.id), self._college_code)
        return []


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
    """Chunk 최종화: upsert/checkpoint 후 후속 처리 정책에 따라 전달."""
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
    _dispatch_chunk_result_sync(
        session,
        ids,
        on_chunk_processed=on_chunk_processed,
        notice_ids_to_process=notice_ids_to_process,
    )
    return n


def _dispatch_chunk_result_sync(
    session: Session,
    ids: list[uuid.UUID],
    *,
    on_chunk_processed: Callable[[list[uuid.UUID]], None] | None,
    notice_ids_to_process: list[uuid.UUID],
) -> None:
    """
    Chunk 처리 경계 정책:
    - on_chunk_processed 없음: 메모리 리스트에 적재(최종 커밋은 상위 호출자).
    - on_chunk_processed 있음: chunk 단위 DB commit/expunge 후 enqueue 콜백 호출.
    """
    if on_chunk_processed is not None:
        # Chunk 단위 커밋 지점: 콜백(예: AI enqueue)이 실패해도 upsert 결과는 추적 가능.
        session.commit()
        session.expunge_all()
        on_chunk_processed(ids)
        return
    notice_ids_to_process.extend(ids)


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
    from app.core.logging_context import set_request_context

    set_request_context(
        college_code=college_code,
        run_id=str(run_id) if run_id else "",
        task_id=task_id or "",
        phase=CrawlPhase.LIST.value,
    )
    try:
        links_raw = get_links_fn(list_url)
    except Exception as e:
        set_request_context(event_code=EVENT_LIST_FETCH_FAILED, phase=CrawlPhase.LIST.value)
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
        set_gauge(
            CRAWL_PIPELINE_PEAK_PENDING_DRAFTS,
            0.0,
            labels={"college_code": college_code},
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
    peak_pending_drafts = 0
    try:
        try:
            set_request_context(phase=CrawlPhase.SCRAPE.value)
            for payload in adapter.collect_payloads(
                links=links,
                college_id=college_id,
                scrape_fn=scrape_fn,
                seen=seen,
                cfg=cfg,
                ctx=ctx,
            ):
                chunk.append(payload)
                peak_pending_drafts = max(peak_pending_drafts, len(chunk))
                if len(chunk) >= cfg.upsert_chunk_size:
                    set_request_context(phase=CrawlPhase.UPSERT.value)
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
                    set_request_context(phase=CrawlPhase.SCRAPE.value)
            if chunk:
                peak_pending_drafts = max(peak_pending_drafts, len(chunk))
                set_request_context(phase=CrawlPhase.UPSERT.value)
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
            set_request_context(event_code=EVENT_PARSE_FAILED, phase=CrawlPhase.SCRAPE.value)
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
        "crawl finished college_code=%s total_links=%d upserted=%d peak_pending_drafts=%d",
        college_code,
        total_links,
        total_upserted,
        peak_pending_drafts,
        extra={
            "college_code": college_code,
            "total_links": total_links,
            "upserted": total_upserted,
            "peak_pending_drafts": peak_pending_drafts,
        },
    )
    set_gauge(
        CRAWL_PIPELINE_PEAK_PENDING_DRAFTS,
        float(peak_pending_drafts),
        labels={"college_code": college_code},
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
    ingestion_attempt_id: uuid.UUID | None = None,
) -> tuple[int, list[uuid.UUID]]:
    """
    단과대 1개 크롤 (동기, Celery 워커 전용). college_sources·레지스트리로 list_url·모듈 해석.
    crawl_split_crawl_and_process=True이고 ingestion_attempt_id가 있으면 DeferredBatchCrawlAdapter.
    """
    from app.services.crawl.source_resolution import resolve_crawl_module_list_url_and_source_sync

    college, _src, module_name, list_url = resolve_crawl_module_list_url_and_source_sync(session, college_code)
    get_links_fn, scrape_fn = get_crawler(module_name)
    cfg = _load_crawl_runtime_config()
    use_deferred = bool(
        settings.crawl_split_crawl_and_process and ingestion_attempt_id is not None,
    )
    if use_deferred:
        seq: list[int] = [0]
        adapter: _SyncCrawlAdapter = DeferredBatchCrawlAdapter(
            attempt_id=ingestion_attempt_id,
            college_code=college_code,
            sequence_counter=seq,
        )
    else:
        adapter = _DefaultSyncCrawlAdapter()
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
        adapter=adapter,
    )
