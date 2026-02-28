"""
크롤 디스패처/서비스: config → get_*_links / scrape_*_detail, 1초 딜레이, external_id·content_hash → Repository.
HTTP 미의존. 비동기(웹)·동기(워커) 세션 모두 지원.

트랜잭션 경계: DB 트랜잭션(시작/커밋/롤백)은 이 오케스트레이터 레이어에서만 통제한다.
Repository·파서는 이미 열린 세션으로 쿼리만 수행하며, 세션 생명주기는 호출자(오케스트레이터)가 소유한다.
"""

import asyncio
import json
import logging
import threading
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from bs4 import BeautifulSoup
from requests.exceptions import RequestException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from tenacity import (
    AsyncRetrying,
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import settings
from app.core.constants import CrawlRunStatus
from app.core.crawl_http import HtmlTooLargeError
from app.core.crawl_rate_limit import (
    get_host_rate_limiter_async,
    get_host_rate_limiter_sync,
    host_from_url,
)
from app.core.crawler_config import COLLEGE_CODE_TO_MODULE, CRAWLER_CONFIG, get_crawler, get_crawler_async
from app.core.redis import get_shared_sync_redis_client
from app.repositories.college_repository import (
    get_by_external_id as get_college_by_external_id,
)
from app.repositories.college_repository import (
    get_by_external_id_sync as get_college_by_external_id_sync,
)
from app.repositories.crawl_run_repository import (
    create_or_update_crawl_run_sync,
    ensure_crawl_run_task_sync,
    update_crawl_run_sync,
)
from app.domain.contracts.crawl_contracts import NoticeDraft
from app.repositories.notice_repository import (
    upsert_notices_bulk,
    upsert_notices_bulk_sync,
)
from app.services.crawl_payload import _external_id_from_url, build_notice_payload
from app.services.crawl_policy import (
    CrawlErrorTracker,
    CrawlThresholdExceeded,
)
from app.services.crawlers.base import ScrapeResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScrapeAttemptResult:
    """한 건 스크랩 시도 결과. (post, detail_url, data, exc) 튜플 대신 이름으로 접근."""

    post: dict
    detail_url: str
    data: ScrapeResult | None
    exc: Exception | None


@dataclass(frozen=True, slots=True)
class CrawlRuntimeConfig:
    polite_delay_seconds: float
    page_timeout_seconds: float
    upsert_chunk_size: int
    collect_sync_max_workers: int
    collect_in_flight_limit: int
    max_links_per_run: int
    collect_async_concurrency: int
    crawl_seen_max_size: int


_crawl_runtime_config_cache: CrawlRuntimeConfig | None = None


def _load_crawl_runtime_config() -> CrawlRuntimeConfig:
    """크롤 런타임 설정을 프로세스당 1회만 로드하고 캐시. 재시작 없이 변경할 일이 없으므로 기동 시 1회 로드로 성능 유리."""
    global _crawl_runtime_config_cache
    if _crawl_runtime_config_cache is None:
        _crawl_runtime_config_cache = CrawlRuntimeConfig(
            polite_delay_seconds=settings.polite_delay_seconds,
            page_timeout_seconds=settings.crawl_page_timeout_seconds,
            upsert_chunk_size=settings.crawl_upsert_chunk_size,
            collect_sync_max_workers=settings.crawl_collect_sync_max_workers,
            collect_in_flight_limit=settings.crawl_collect_in_flight_limit,
            max_links_per_run=settings.crawl_max_links_per_run,
            collect_async_concurrency=settings.crawl_collect_async_concurrency,
            crawl_seen_max_size=settings.crawl_seen_max_size,
        )
    return _crawl_runtime_config_cache

# 요청/페이지 간 최소 딜레이(초). 부하·IP 차단 완화. .env POLITE_DELAY_SECONDS로 오버라이드 가능.

# 비동기 크롤 페이지 타임아웃(초).

# sync 경로 청크 단위 upsert 크기. commit 후 expunge_all로 세션 Identity Map 비우기(E1).

# 상세 페이지 병렬 수집 시 최대 워커 수 (rate limit은 메인 스레드에서만 적용).
# 동기 수집 시 동시에 유지할 Future 상한. O(N) 메모리 방지.
# Run당 링크 수 상한. 초과 시 잘라서 처리해 단일 노드 OOM 방지(선제 대응). 스트리밍/Redis 큐는 추후 확장.
# 비동기 수집 시 전체 동시 요청 수. 호스트별 delay는 유지.

# Bounded Seen Set: 최대 보유 개수. 초과 시 가장 오래된 항목 evict. OOM 방지.

# 비동기 재시도: tenacity wait_exponential_jitter 사용. Thundering Herd 방지.
CRAWL_RETRY_BASE_SEC = 1.0
CRAWL_RETRY_MAX_SEC = 60.0
CRAWL_RETRY_MAX_ATTEMPTS = 5
# tenacity wait: (initial, max) + jitter. retry_state.attempt_number 기반.
_crawl_retry_wait = wait_exponential_jitter(
    initial=CRAWL_RETRY_BASE_SEC,
    max=CRAWL_RETRY_MAX_SEC,
    jitter=1.0,
)


class _BoundedSeenSet:
    """최대 max_size개 external_id만 유지. 초과 시 가장 오래된 항목 evict. O(1) add/contains."""

    __slots__ = ("_deque", "_set", "_max_size")

    def __init__(self, max_size: int | None = None) -> None:
        self._deque: deque[str] = deque()
        self._set: set[str] = set()
        self._max_size = max_size or settings.crawl_seen_max_size

    def add(self, x: str) -> None:
        if x in self._set:
            return
        while len(self._set) >= self._max_size and self._deque:
            oldest = self._deque.popleft()
            self._set.discard(oldest)
        self._deque.append(x)
        self._set.add(x)

    def __contains__(self, x: str) -> bool:
        return x in self._set


CRAWL_SEEN_REDIS_KEY_PREFIX = "dicee:crawl_seen:"
CRAWL_SEEN_REDIS_TTL_SECONDS = 3600  # Run 단위 1시간 (멀티 워커 간 중복 크롤 방지)


class _RedisSeenSet:
    """
    Redis SET 기반 분산 Seen Set. run_id 단위로 워커 간 이미 본 URL 공유.
    멀티 워커 환경에서 동일 URL 중복 크롤 방지(필수). add/__contains__ 인터페이스.
    생성자에서는 I/O 없음. 첫 add/__contains__ 호출 시 lazy로 Redis 클라이언트 연결.
    """

    __slots__ = ("_key", "_client", "_ttl", "_closed", "_required", "_run_id")

    def __init__(
        self,
        run_id: uuid.UUID,
        _redis_url: str,
        ttl_seconds: int = CRAWL_SEEN_REDIS_TTL_SECONDS,
        *,
        required: bool = False,
    ) -> None:
        self._key = f"{CRAWL_SEEN_REDIS_KEY_PREFIX}{run_id}"
        self._run_id = run_id
        self._ttl = ttl_seconds
        self._closed = False
        self._required = required
        self._client: Any | None = None

    def _ensure_client(self) -> None:
        """첫 사용 시점에 Redis 클라이언트 연결. 생성자 I/O 분리용."""
        if self._client is not None or self._closed:
            return
        try:
            self._client = get_shared_sync_redis_client()
        except Exception as e:
            if self._required:
                raise RuntimeError(
                    f"Redis Seen Set required but connection failed (run_id={self._run_id}): {e}"
                ) from e
            logger.warning("RedisSeenSet connect failed: %s; falling back to in-memory", e)
        if self._client is None and self._required:
            raise RuntimeError(
                f"Redis Seen Set required but connection failed (run_id={self._run_id}): redis client unavailable"
            )

    def add(self, x: str) -> None:
        self._ensure_client()
        if self._client is None:
            if self._required:
                raise RuntimeError("Redis Seen Set required but client is unavailable (init failed).")
            return
        try:
            pipe = self._client.pipeline()
            pipe.sadd(self._key, x)
            pipe.expire(self._key, self._ttl)
            pipe.execute()
        except Exception as e:
            if self._required:
                raise RuntimeError(f"Redis Seen Set add failed (required): {e}") from e
            logger.warning("RedisSeenSet add failed: %s", e)

    def __contains__(self, x: str) -> bool:
        self._ensure_client()
        if self._client is None:
            if self._required:
                raise RuntimeError("Redis Seen Set required but client is unavailable (init failed).")
            return False
        try:
            return bool(self._client.sismember(self._key, x))
        except Exception as e:
            if self._required:
                raise RuntimeError(f"Redis Seen Set __contains__ failed (required): {e}") from e
            logger.warning("RedisSeenSet __contains__ failed: %s", e)
            return False

    def close(self) -> None:
        if getattr(self, "_closed", True) or self._client is None:
            return
        self._closed = True


_SeenSet = set[str] | _BoundedSeenSet | _RedisSeenSet


def _resolve_module_and_list_url(college_code: str) -> tuple[str, str]:
    module_name = COLLEGE_CODE_TO_MODULE.get(college_code)
    if not module_name:
        raise ValueError(f"No crawler module for college: {college_code}")
    config = CRAWLER_CONFIG.get(module_name)
    if not config or not config.get("url"):
        raise ValueError(f"No crawler config or url for: {module_name}")
    return module_name, config["url"]


def _cap_links_for_run(links_raw: list[dict], college_code: str, max_links: int) -> list[dict]:
    if len(links_raw) > max_links:
        logger.warning(
            "Links capped for OOM prevention: college_code=%s total=%d cap=%d",
            college_code,
            len(links_raw),
            max_links,
        )
    return links_raw[:max_links]


def _init_seen_set(
    *,
    run_id: uuid.UUID | None,
    redis_url: str,
    redis_required: bool,
    seen_max_size: int,
) -> _BoundedSeenSet | _RedisSeenSet:
    if run_id and redis_url:
        return _RedisSeenSet(
            run_id,
            redis_url,
            CRAWL_SEEN_REDIS_TTL_SECONDS,
            required=redis_required,
        )
    return _BoundedSeenSet(seen_max_size)


class _SyncCrawlAdapter(Protocol):
    def collect_payloads(
        self,
        *,
        links: list[dict],
        college_id: uuid.UUID,
        scrape_fn: Callable,
        seen: _SeenSet,
        cfg: CrawlRuntimeConfig,
    ) -> Iterator[NoticeDraft]: ...

    def upsert_chunk(self, session: Session, chunk: list[NoticeDraft]) -> list[uuid.UUID]: ...


class _AsyncCrawlAdapter(Protocol):
    def collect_payloads(
        self,
        *,
        client: httpx.AsyncClient,
        links: list[dict],
        college_id: uuid.UUID,
        scrape_async_fn: Callable,
        seen: _SeenSet,
        cfg: CrawlRuntimeConfig,
    ) -> AsyncIterator[NoticeDraft]: ...

    async def upsert_chunk(
        self,
        session: AsyncSession,
        chunk: list[NoticeDraft],
    ) -> list[uuid.UUID]: ...


class _DefaultSyncCrawlAdapter:
    def collect_payloads(
        self,
        *,
        links: list[dict],
        college_id: uuid.UUID,
        scrape_fn: Callable,
        seen: _SeenSet,
        cfg: CrawlRuntimeConfig,
    ) -> Iterator[NoticeDraft]:
        return _collect_payloads_sync(
            links,
            college_id,
            scrape_fn,
            cfg.polite_delay_seconds,
            seen=seen,
            max_workers=cfg.collect_sync_max_workers,
            in_flight_limit=cfg.collect_in_flight_limit,
        )

    def upsert_chunk(self, session: Session, chunk: list[NoticeDraft]) -> list[uuid.UUID]:
        return upsert_notices_bulk_sync(session, chunk)


class _DefaultAsyncCrawlAdapter:
    async def collect_payloads(
        self,
        *,
        client: httpx.AsyncClient,
        links: list[dict],
        college_id: uuid.UUID,
        scrape_async_fn: Callable,
        seen: _SeenSet,
        cfg: CrawlRuntimeConfig,
    ) -> AsyncIterator[NoticeDraft]:
        async for payload in _collect_payloads_async(
            client,
            links,
            college_id,
            scrape_async_fn,
            cfg.polite_delay_seconds,
            seen=seen,
            concurrency=cfg.collect_async_concurrency,
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
    seen = _init_seen_set(
        run_id=None,
        redis_url="",
        redis_required=False,
        seen_max_size=cfg.crawl_seen_max_size,
    )
    async with httpx.AsyncClient(timeout=cfg.page_timeout_seconds) as client:
        links_raw = await get_links_async_fn(client, list_url)
        links = _cap_links_for_run(links_raw, college_code, cfg.max_links_per_run)
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


def _scrape_one_sync(post: dict, scrape_fn: Callable) -> ScrapeAttemptResult:
    """워커용: scrape_fn(detail_url) 호출. data는 ScrapeResult 또는 None."""
    detail_url = post.get("url") or ""
    try:
        data = scrape_fn(detail_url)
        return ScrapeAttemptResult(post=post, detail_url=detail_url, data=data, exc=None)
    except Exception as e:
        return ScrapeAttemptResult(post=post, detail_url=detail_url, data=None, exc=e)


# 네트워크/타임아웃 예외 (sync: RequestException, async: httpx.HTTPError/TimeoutException)
_NETWORK_EXC_TYPES = (
    TimeoutError,
    OSError,
    ConnectionError,
    RequestException,
    httpx.HTTPError,
    httpx.TimeoutException,
)


async def _fetch_one_async(
    client: httpx.AsyncClient,
    post: dict,
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
    post: dict,
    scrape_async_fn,
    rate_limiter,
    sem: asyncio.Semaphore,
) -> ScrapeAttemptResult:
    """한 건 비동기 스크랩 + 네트워크/타임아웃 시 tenacity 재시도. 재시도 소진 시 마지막 결과 반환."""
    last_result: ScrapeAttemptResult | None = None
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(CRAWL_RETRY_MAX_ATTEMPTS),
        wait=_crawl_retry_wait,
        retry=retry_if_exception_type(_NETWORK_EXC_TYPES),
        reraise=False,
    ):
        with attempt:
            last_result = await _fetch_one_async(
                client, post, scrape_async_fn, rate_limiter, sem
            )
            if last_result.exc is not None and isinstance(
                last_result.exc, _NETWORK_EXC_TYPES
            ):
                raise last_result.exc
            return last_result
    if last_result is not None:
        return last_result
    return ScrapeAttemptResult(
        post=post, detail_url=post.get("url") or "", data=None, exc=None
    )


def _process_scrape_result(
    post: dict,
    detail_url: str,
    data: ScrapeResult | None,
    exc: Exception | None,
    college_id: uuid.UUID,
    seen: set[str] | _BoundedSeenSet | _RedisSeenSet,
    tracker: CrawlErrorTracker,
) -> tuple[NoticeDraft | None, CrawlThresholdExceeded | Exception | None]:
    """
    한 건 스크랩 결과 처리. CrawlErrorTracker로 상태 캡슐화. sync/async 공통.
    반환: (NoticeDraft 또는 None, raise할 예외 또는 None).
    """
    tracker.record_attempt()
    if exc is not None:
        if isinstance(exc, _NETWORK_EXC_TYPES):
            logger.warning(
                "scrape failed (timeout/network): url=%s error=%s",
                detail_url[:200] if detail_url else "",
                exc,
                exc_info=True,
            )
            tracker.record_network_or_skip()
            return (None, None)
        if isinstance(exc, HtmlTooLargeError):
            logger.warning(
                "scrape skipped (body too large): url=%s %s",
                detail_url[:200] if detail_url else "",
                exc,
            )
            tracker.record_network_or_skip()
            return (None, None)
        if isinstance(exc, ValueError | KeyError | AttributeError | TypeError):
            logger.warning(
                "scrape failed (parser): url=%s error=%s",
                detail_url[:200] if detail_url else "",
                exc,
                exc_info=True,
            )
            threshold_exc = tracker.record_parser_failure()
            return (None, threshold_exc)
        return (None, exc)
    assert data is not None
    tracker.record_success()
    title = data.title or ""
    date_str = data.date_str
    html_content = data.html_content
    images, attachments = data.images, data.attachments
    external_id = post.get("no") or _external_id_from_url(detail_url)
    if external_id in seen:
        return (None, None)
    body_text_for_hash = (
        BeautifulSoup(html_content, "html.parser").get_text(separator="\n", strip=True)
        if html_content
        else ""
    )
    payload = build_notice_payload(
        college_id,
        post,
        detail_url,
        title,
        date_str,
        html_content,
        images,
        attachments,
        body_text_for_hash=body_text_for_hash or None,
        external_id=external_id,
    )
    if payload is None:
        return (None, None)
    seen.add(external_id)
    return (payload, None)


def _scrape_one_sync_with_sem(
    post: dict,
    scrape_fn: Callable,
    rate_limiter,
    sem: threading.BoundedSemaphore,
) -> ScrapeAttemptResult:
    """BoundedSemaphore로 동시 스크랩 수 제한. 워커 스레드에서 호출."""
    sem.acquire()
    try:
        detail_url = post.get("url") or ""
        host = host_from_url(detail_url) or "_"
        last_result: ScrapeAttemptResult | None = None
        try:
            for attempt in Retrying(
                stop=stop_after_attempt(CRAWL_RETRY_MAX_ATTEMPTS),
                wait=_crawl_retry_wait,
                retry=retry_if_exception_type(_NETWORK_EXC_TYPES),
                reraise=False,
            ):
                with attempt:
                    rate_limiter.wait_sync(host)
                    last_result = _scrape_one_sync(post, scrape_fn)
                    if last_result.exc is not None and isinstance(
                        last_result.exc, _NETWORK_EXC_TYPES
                    ):
                        raise last_result.exc
                    return last_result
        except RetryError:
            pass
        if last_result is not None:
            return last_result
        return ScrapeAttemptResult(
            post=post, detail_url=detail_url, data=None, exc=None
        )
    finally:
        sem.release()


def _collect_payloads_sync(
    links: list[dict],
    college_id: uuid.UUID,
    scrape_fn: Callable,
    delay_sec: float,
    *,
    max_workers: int,
    in_flight_limit: int,
    seen: set[str] | _BoundedSeenSet | _RedisSeenSet | None = None,
) -> Iterator[NoticeDraft]:
    """
    동기: Bounded in-flight(K)로 링크 처리. Semaphore + as_completed로 제어 단순화.
    O(K) 메모리. 파서/구조 예외는 임계치 초과 시 CrawlThresholdExceeded raise.
    """
    if seen is None:
        seen = set()
    rate_limiter = get_host_rate_limiter_sync(delay_sec)
    tracker = CrawlErrorTracker()
    remaining = deque(links)
    sem = threading.BoundedSemaphore(in_flight_limit)

    def submit_one() -> None:
        if not remaining:
            return
        post = remaining.popleft()
        fut = executor.submit(_scrape_one_sync_with_sem, post, scrape_fn, rate_limiter, sem)
        futures[fut] = post

    executor = ThreadPoolExecutor(max_workers=max_workers)
    futures: dict = {}
    try:
        for _ in range(min(in_flight_limit, len(remaining))):
            if not remaining:
                break
            submit_one()

        while futures:
            for fut in as_completed(set(futures.keys())):
                futures.pop(fut)
                try:
                    result = fut.result()
                except Exception as e:
                    logger.warning("scrape future exception: %s", e, exc_info=True)
                    submit_one()
                    continue
                payload, raise_exc = _process_scrape_result(
                    result.post,
                    result.detail_url,
                    result.data,
                    result.exc,
                    college_id,
                    seen,
                    tracker,
                )
                if raise_exc is not None:
                    raise raise_exc
                if payload is not None:
                    yield payload
                submit_one()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        close_fn = getattr(rate_limiter, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass


async def _collect_payloads_async(
    client: httpx.AsyncClient,
    links: list[dict],
    college_id: uuid.UUID,
    scrape_async_fn,
    delay_sec: float,
    *,
    concurrency: int,
    seen: set[str] | _BoundedSeenSet | _RedisSeenSet | None = None,
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

    def _task(post: dict) -> asyncio.Task:
        return asyncio.create_task(
            _fetch_one_with_retry(client, post, scrape_async_fn, rate_limiter, sem)
        )

    def _refill_pending() -> None:
        while len(pending) < concurrency and remaining:
            pending.add(_task(remaining.popleft()))

    pending: set[asyncio.Task] = set()
    for _ in range(min(concurrency, len(remaining))):
        if not remaining:
            break
        pending.add(_task(remaining.popleft()))

    try:
        while pending or remaining:
            _refill_pending()
            if not pending:
                continue
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                try:
                    result = task.result()
                except Exception as e:
                    logger.warning("scrape task exception: %s", e, exc_info=True)
                    if remaining:
                        pending.add(_task(remaining.popleft()))
                    continue
                if result.exc is not None and isinstance(
                    result.exc, _NETWORK_EXC_TYPES
                ):
                    tracker.record_attempt()
                    tracker.record_network_or_skip()
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
                # 종료 실패는 치명적이지 않으므로 무시
                pass


def _finalize_chunk_sync(
    session: Session,
    adapter: _SyncCrawlAdapter,
    chunk: list[NoticeDraft],
    *,
    on_chunk_processed: Callable[[list[uuid.UUID]], None] | None,
    notice_ids_to_process: list[uuid.UUID],
) -> int:
    ids = adapter.upsert_chunk(session, chunk)
    chunk.clear()
    if on_chunk_processed is not None:
        session.commit()
        session.expunge_all()
        on_chunk_processed(ids)
    else:
        notice_ids_to_process.extend(ids)
    return len(ids)


def _run_crawl_pipeline_sync(
    session: Session,
    *,
    college_code: str,
    college_id: uuid.UUID,
    list_url: str,
    get_links_fn: Callable,
    scrape_fn: Callable,
    run_id: uuid.UUID | None,
    on_chunk_processed: Callable[[list[uuid.UUID]], None] | None,
    cfg: CrawlRuntimeConfig,
    adapter: _SyncCrawlAdapter,
) -> tuple[int, list[uuid.UUID]]:
    links_raw = get_links_fn(list_url)
    links = _cap_links_for_run(links_raw, college_code, cfg.max_links_per_run)
    total_links = len(links)
    if not links:
        logger.info(
            "crawl finished college_code=%s total_links=0 upserted=0",
            college_code,
        )
        return (0, [])

    raw_redis = (settings.redis.redis_url or "").strip()
    crawl_seen_required = settings.redis.redis_crawl_seen_required
    seen = _init_seen_set(
        run_id=run_id,
        redis_url=raw_redis,
        redis_required=crawl_seen_required,
        seen_max_size=cfg.crawl_seen_max_size,
    )
    notice_ids_to_process: list[uuid.UUID] = []
    total_upserted = 0
    chunk: list[NoticeDraft] = []
    try:
        for payload in adapter.collect_payloads(
            links=links,
            college_id=college_id,
            scrape_fn=scrape_fn,
            seen=seen,
            cfg=cfg,
        ):
            chunk.append(payload)
            if len(chunk) >= cfg.upsert_chunk_size:
                total_upserted += _finalize_chunk_sync(
                    session,
                    adapter,
                    chunk,
                    on_chunk_processed=on_chunk_processed,
                    notice_ids_to_process=notice_ids_to_process,
                )
        if chunk:
            total_upserted += _finalize_chunk_sync(
                session,
                adapter,
                chunk,
                on_chunk_processed=on_chunk_processed,
                notice_ids_to_process=notice_ids_to_process,
            )
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
    on_chunk_processed: Callable[[list[uuid.UUID]], None] | None = None,
) -> tuple[int, list[uuid.UUID]]:
    """
    단과대 1개 크롤 (동기, Celery 워커 전용). 동기 DB 세션·Repository 사용.
    get_*_links / (1초 sleep) / scrape_*_detail → upsert_notice_sync.
    run_id가 있고 REDIS_URL이 있으면 Redis 분산 Seen Set 사용(멀티 워커 중복 크롤 방지).
    on_chunk_processed: 청크 upsert 직후 호출(메모리 누적 없이 즉시 enqueue용). None이면 notice_id 목록 반환.
    반환: (upsert한 개수, AI 처리 대상 notice_id 목록). on_chunk_processed 사용 시 목록은 [].
    트랜잭션 경계: 호출자(run_crawl_job_sync 등)가 세션을 소유. 이 함수는 전달받은 세션으로 Repository만 호출.
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
        on_chunk_processed=on_chunk_processed,
        cfg=cfg,
        adapter=_DefaultSyncCrawlAdapter(),
    )


CRAWL_FAILURE_REDIS_KEY_PREFIX = "dicee:crawl_failure:"
CRAWL_FAILURE_REDIS_TTL_SECONDS = 86400 * 7  # 7일 (중앙 추적·모니터링용)


def _record_crawl_failure_fallback(
    run_id: uuid.UUID,
    task_id: str,
    college_code: str,
    error_message: str,
) -> None:
    """
    DB 장애 시 실패 컨텍스트를 Redis에 기록해 중앙에서 추적 가능하게 함.
    Redis 미설정/장애 시 로그만 남기고 반환(예외 전파하지 않음).
    """
    raw_url = (settings.redis.redis_url or "").strip()
    if not raw_url:
        logger.warning(
            "Crawl failure fallback skipped: REDIS_URL not set (run_id=%s task_id=%s college_code=%s)",
            run_id,
            task_id,
            college_code,
        )
        return
    try:
        client = get_shared_sync_redis_client()
        if client is None:
            raise RuntimeError("shared redis client unavailable")
        key = f"{CRAWL_FAILURE_REDIS_KEY_PREFIX}{run_id}"
        payload = {
            "run_id": str(run_id),
            "task_id": task_id,
            "college_code": college_code,
            "error_message": error_message[:2000],
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        client.set(key, json.dumps(payload), ex=CRAWL_FAILURE_REDIS_TTL_SECONDS)
        logger.info(
            "Crawl failure context recorded to Redis (run_id=%s key=%s)",
            run_id,
            key,
        )
    except Exception as redis_err:
        logger.warning(
            "Failed to record crawl failure to Redis (run_id=%s): %s",
            run_id,
            redis_err,
            exc_info=True,
        )


def run_crawl_job_sync(
    session: Session,
    college_code: str,
    task_id: str,
    on_chunk_processed: Callable[[list[uuid.UUID]], None],
) -> tuple[int, int]:
    """
    크롤 작업 한 건 실행 (college 조회 + crawl_run 생성/갱신 + crawl_college_sync).
    서비스 레이어 단일 진입점: tasks에서 college/crawl_run repository 직접 주입 없이 사용.
    반환: (upserted 개수, enqueued_ai 개수).
    트랜잭션 경계: 세션·커밋/롤백은 이 오케스트레이터에서만 통제. Repository는 전달받은 세션으로 쿼리만 수행.
    """

    college = get_college_by_external_id_sync(session, college_code)
    if not college:
        raise ValueError(f"College not found: {college_code}")
    run_id = ensure_crawl_run_task_sync(session, task_id)
    create_or_update_crawl_run_sync(session, run_id, college.id)
    session.commit()
    try:
        count, _ = crawl_college_sync(
            session,
            college_code,
            run_id=run_id,
            on_chunk_processed=on_chunk_processed,
        )
        update_crawl_run_sync(
            session,
            run_id,
            finished_at=datetime.now(UTC),
            status=CrawlRunStatus.SUCCESS.value,
            notices_upserted=count,
        )
        session.commit()
        return (count, count)
    except Exception as e:
        # 실패한 트랜잭션 초기화 (PendingRollbackError 방지)
        session.rollback()
        error_msg = (str(e))[:2000]
        # 1) 동일 세션으로 FAILED 기록 시도 (DB 장애가 아닐 때 성공)
        try:
            update_crawl_run_sync(
                session,
                run_id,
                finished_at=datetime.now(UTC),
                status=CrawlRunStatus.FAILED.value,
                error_message=error_msg,
            )
            session.commit()
        except Exception as record_err:
            # 2) 동일 세션도 실패(DB 장애·풀 고갈) 시 Redis 등 외부 저장소에 실패 컨텍스트 격리(중앙 추적용)
            logger.warning(
                "Failed to record crawl run FAILED in DB (run_id=%s): %s",
                run_id,
                record_err,
                exc_info=True,
            )
            _record_crawl_failure_fallback(run_id, task_id, college_code, error_msg)
        raise
