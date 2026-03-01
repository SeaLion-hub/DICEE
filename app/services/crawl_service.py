"""
크롤 디스패처/서비스: config → get_*_links / scrape_*_detail.
Sync 진입점은 app.services.crawl 패키지에서 구현·re-export. 이 모듈은 async 경로 + re-export만 유지.
테스트가 crawl_service 모듈 속성으로 패치/접근하므로 아래 re-export 유지.
"""

from app.core.config import settings  # noqa: F401 (re-export for tests)
from app.core.crawl_rate_limit import get_host_rate_limiter_sync  # noqa: F401
from app.core.crawler_config import get_crawler  # noqa: F401
from app.core.redis import get_shared_sync_redis_client  # noqa: F401
from app.repositories.college_repository import (
    get_by_external_id_sync as get_college_by_external_id_sync,  # noqa: F401
)
from app.repositories.crawl_run_repository import ensure_crawl_run_task_sync  # noqa: F401
from app.services.crawl.collect_sync import (
    _collect_payloads_sync,  # noqa: F401
    _get_http_status_code,  # noqa: F401
    _process_scrape_result,
    _scrape_one_sync,  # noqa: F401
    _scrape_one_sync_with_sem,  # noqa: F401
)
from app.services.crawl.entrypoints import (
    crawl_college_sync,
    handle_crawl_failure_composite,
    run_crawl_job_sync,
)
from app.services.crawl.failure import (
    CRAWL_FAILURE_REDIS_KEY_PREFIX,  # noqa: F401
    CRAWL_FAILURE_REDIS_TTL_SECONDS,  # noqa: F401
    _record_crawl_failure_fallback,  # noqa: F401
)
from app.services.crawl.pipeline_sync import (  # noqa: F401
    _DefaultSyncCrawlAdapter,
    _run_crawl_pipeline_sync,
)
from app.services.crawl.runtime import (
    CrawlRuntimeConfig,
    _BoundedSeenSet,
    _cap_links_for_run,
    _RedisSeenSet,
)

__all__ = [
    "crawl_college_sync",
    "handle_crawl_failure_composite",
    "run_crawl_job_sync",
]

import asyncio
import logging
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Protocol, cast

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt

from app.core.crawl_rate_limit import get_host_rate_limiter_async, host_from_url
from app.core.crawler_config import get_crawler_async
from app.domain.contracts.crawl_contracts import (
    EVENT_LIST_FETCH_FAILED,
    CrawlLogContext,
    CrawlPhase,
    LinkItem,
    NoticeDraft,
)
from app.repositories.college_repository import get_by_external_id as get_college_by_external_id
from app.repositories.notice_repository import upsert_notices_bulk
from app.services.crawl.collect_sync import (
    ScrapeAttemptResult,
    _is_retryable,
    _is_skippable,
)
from app.services.crawl.runtime import (
    CRAWL_RETRY_MAX_ATTEMPTS,
    _crawl_retry_wait,
    _init_seen_set_async,
    _load_crawl_runtime_config,
    _resolve_module_and_list_url,
)
from app.services.crawl_policy import CrawlErrorTracker

logger = logging.getLogger(__name__)


class _AsyncCrawlAdapter(Protocol):
    def collect_payloads(
        self,
        *,
        client: httpx.AsyncClient,
        links: list[LinkItem],
        college_id: uuid.UUID,
        scrape_async_fn: Callable,
        seen: _BoundedSeenSet,
        cfg: CrawlRuntimeConfig,
        ctx: CrawlLogContext,
    ) -> AsyncIterator[NoticeDraft]: ...

    async def upsert_chunk(
        self,
        session: AsyncSession,
        chunk: list[NoticeDraft],
    ) -> list[uuid.UUID]: ...


class _DefaultAsyncCrawlAdapter:
    async def collect_payloads(
        self,
        *,
        client: httpx.AsyncClient,
        links: list[LinkItem],
        college_id: uuid.UUID,
        scrape_async_fn: Callable,
        seen: _BoundedSeenSet,
        cfg: CrawlRuntimeConfig,
        ctx: CrawlLogContext,
    ) -> AsyncIterator[NoticeDraft]:
        async for payload in _collect_payloads_async(
            client,
            links,
            college_id,
            scrape_async_fn,
            cfg.polite_delay_seconds,
            seen=seen,
            concurrency=cfg.collect_async_concurrency,
            ctx=ctx,
        ):
            yield payload

    async def upsert_chunk(
        self,
        session: AsyncSession,
        chunk: list[NoticeDraft],
    ) -> list[uuid.UUID]:
        return await upsert_notices_bulk(session, chunk)


async def _finalize_chunk_async(
    session: AsyncSession,
    adapter: _AsyncCrawlAdapter,
    chunk: list[NoticeDraft],
) -> int:
    ids = await adapter.upsert_chunk(session, chunk)
    chunk.clear()
    return len(ids)


async def _run_crawl_pipeline_async(
    session: AsyncSession,
    *,
    college_code: str,
    college_id: uuid.UUID,
    list_url: str,
    get_links_async_fn: Callable,
    scrape_async_fn: Callable,
    cfg: CrawlRuntimeConfig,
    adapter: _AsyncCrawlAdapter,
) -> int:
    ctx = CrawlLogContext(college_code=college_code)
    seen = _init_seen_set_async(cfg.crawl_seen_max_size)
    async with httpx.AsyncClient(timeout=cfg.page_timeout_seconds) as client:
        try:
            links_raw = await get_links_async_fn(client, list_url)
        except Exception as e:
            from app.core.logging_context import set_request_context

            set_request_context(event_code=EVENT_LIST_FETCH_FAILED)
            log_extra = {
                "college_code": college_code,
                "phase": CrawlPhase.LIST.value,
                "event_code": EVENT_LIST_FETCH_FAILED,
            }
            logger.warning("crawl list fetch failed (async): %s", e, exc_info=True, extra=log_extra)
            raise
        links = _cap_links_for_run(cast(list[LinkItem], links_raw), college_code, cfg.max_links_per_run)
        total_links = len(links)
        if not links:
            logger.info(
                "crawl finished college_code=%s total_links=0 upserted=0",
                college_code,
            )
            return 0
        total_count = 0
        chunk: list[NoticeDraft] = []
        async for payload in adapter.collect_payloads(
            client=client,
            links=links,
            college_id=college_id,
            scrape_async_fn=scrape_async_fn,
            seen=seen,
            cfg=cfg,
            ctx=ctx,
        ):
            chunk.append(payload)
            if len(chunk) >= cfg.upsert_chunk_size:
                total_count += await _finalize_chunk_async(session, adapter, chunk)
        if chunk:
            total_count += await _finalize_chunk_async(session, adapter, chunk)
        logger.info(
            "crawl finished college_code=%s total_links=%d upserted=%d",
            college_code,
            total_links,
            total_count,
        )
        return total_count


async def crawl_college(session: AsyncSession, college_code: str) -> int:
    """
    단과대 1개 크롤 (완전 비동기). httpx.AsyncClient + get_*_links_async / scrape_*_detail_async.
    asyncio.to_thread 제거. 반환: upsert한 공지 개수.
    """
    college = await get_college_by_external_id(session, college_code)
    if not college:
        raise ValueError(f"College not found: {college_code}")
    module_name, list_url = _resolve_module_and_list_url(college_code)
    get_links_async_fn, scrape_async_fn = get_crawler_async(module_name)
    cfg = _load_crawl_runtime_config()
    return await _run_crawl_pipeline_async(
        session,
        college_code=college_code,
        college_id=college.id,
        list_url=list_url,
        get_links_async_fn=get_links_async_fn,
        scrape_async_fn=scrape_async_fn,
        cfg=cfg,
        adapter=_DefaultAsyncCrawlAdapter(),
    )


async def _fetch_one_async(
    client: httpx.AsyncClient,
    post: LinkItem,
    scrape_async_fn,
    rate_limiter,
    sem: asyncio.Semaphore,
) -> ScrapeAttemptResult:
    """한 건 비동기 스크랩. 모듈 레벨로 분리해 단위 테스트 가능."""
    async with sem:
        detail_url = post.get("url") or ""
        await rate_limiter.wait_async(host_from_url(detail_url) or "_")
        try:
            data = await scrape_async_fn(client, detail_url)
            return ScrapeAttemptResult(post=post, detail_url=detail_url, data=data, exc=None)
        except Exception as e:
            return ScrapeAttemptResult(post=post, detail_url=detail_url, data=None, exc=e)


async def _fetch_one_with_retry(
    client: httpx.AsyncClient,
    post: LinkItem,
    scrape_async_fn,
    rate_limiter,
    sem: asyncio.Semaphore,
) -> ScrapeAttemptResult:
    """한 건 비동기 스크랩. 404/410 스킵(0회 재시도), 408/429/5xx·연결오류 재시도, 그 외 치명은 즉시 반환."""
    last_result: ScrapeAttemptResult | None = None
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(CRAWL_RETRY_MAX_ATTEMPTS),
        wait=_crawl_retry_wait,
        retry=retry_if_exception(_is_retryable),
        reraise=False,
    ):
        with attempt:
            last_result = await _fetch_one_async(client, post, scrape_async_fn, rate_limiter, sem)
            if last_result.exc is None:
                return last_result
            if _is_skippable(last_result.exc):
                return last_result
            if _is_retryable(last_result.exc):
                raise last_result.exc
            return last_result
    if last_result is not None:
        return last_result
    return ScrapeAttemptResult(post=post, detail_url=post.get("url") or "", data=None, exc=None)


async def _collect_payloads_async(
    client: httpx.AsyncClient,
    links: list[LinkItem],
    college_id: uuid.UUID,
    scrape_async_fn,
    delay_sec: float,
    *,
    concurrency: int,
    seen: set[str] | _BoundedSeenSet | _RedisSeenSet | None = None,
    ctx: CrawlLogContext,
) -> AsyncIterator[NoticeDraft]:
    """
    비동기: Semaphore(W) + 호스트별 delay로 제한된 병렬 수집. 1 req/s 직렬 완화.
    파서/구조 예외는 임계치 초과 시 CrawlThresholdExceeded raise.
    """
    if seen is None:
        seen = set()
    rate_limiter = get_host_rate_limiter_async(delay_sec)
    sem = asyncio.Semaphore(concurrency)
    tracker = CrawlErrorTracker()
    remaining = deque(links)

    def _task(post: LinkItem) -> asyncio.Task[ScrapeAttemptResult]:
        return asyncio.create_task(_fetch_one_with_retry(client, post, scrape_async_fn, rate_limiter, sem))

    def _refill_pending() -> None:
        while len(pending) < concurrency and remaining:
            pending.add(_task(remaining.popleft()))

    pending: set[asyncio.Task[ScrapeAttemptResult]] = set()
    for _ in range(min(concurrency, len(remaining))):
        if not remaining:
            break
        pending.add(_task(remaining.popleft()))

    try:
        while pending or remaining:
            _refill_pending()
            if not pending:
                continue
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    result = task.result()
                except Exception as e:
                    logger.warning("scrape task exception: %s", e, exc_info=True)
                    if remaining:
                        pending.add(_task(remaining.popleft()))
                    continue
                payload, raise_exc = _process_scrape_result(
                    result.post,
                    result.detail_url,
                    result.data,
                    result.exc,
                    college_id,
                    seen,
                    tracker,
                    ctx,
                )
                if raise_exc is not None:
                    raise raise_exc
                if payload is not None:
                    yield payload
                if remaining:
                    pending.add(_task(remaining.popleft()))
    finally:
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        aclose_fn = getattr(rate_limiter, "aclose", None)
        if callable(aclose_fn):
            try:
                await aclose_fn()
            except Exception:
                pass
