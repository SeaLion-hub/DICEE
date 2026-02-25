"""
크롤 디스패처/서비스: config → get_*_links / scrape_*_detail, 1초 딜레이, external_id·content_hash → Repository.
HTTP 미의존. 비동기(웹)·동기(워커) 세션 모두 지원.

트랜잭션 경계: DB 트랜잭션(시작/커밋/롤백)은 이 오케스트레이터 레이어에서만 통제한다.
Repository·파서는 이미 열린 세션으로 쿼리만 수행하며, 세션 생명주기는 호출자(오케스트레이터)가 소유한다.
"""

import asyncio
import logging
import random
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

from bs4 import BeautifulSoup
from requests.exceptions import RequestException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import httpx

from app.core.config import settings
from app.core.constants import CrawlRunStatus
from app.core.crawl_http import HtmlTooLargeError
from app.core.crawl_rate_limit import (
    HostRateLimiter,
    get_host_rate_limiter_async,
    get_host_rate_limiter_sync,
    host_from_url,
)
from app.services.crawl_policy import (
    CrawlErrorTracker,
    CrawlThresholdExceeded,
    PARSER_CONSECUTIVE_FAILURES_THRESHOLD,
    PARSER_FAILURE_RATIO_THRESHOLD,
)
from app.core.crawler_config import COLLEGE_CODE_TO_MODULE, CRAWLER_CONFIG, get_crawler, get_crawler_async
from app.services.crawlers.base import ScrapeResult
from app.services.crawl_payload import build_notice_payload, _external_id_from_url
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
from app.repositories.notice_repository import (
    upsert_notices_bulk,
    upsert_notices_bulk_sync,
)

logger = logging.getLogger(__name__)

# 요청/페이지 간 최소 딜레이(초). 부하·IP 차단 완화. .env POLITE_DELAY_SECONDS로 오버라이드 가능.
POLITE_DELAY_SECONDS = settings.polite_delay_seconds

# 비동기 크롤 페이지 타임아웃(초).
CRAWL_PAGE_TIMEOUT_SECONDS = 30

# sync 경로 청크 단위 upsert 크기. commit 후 expunge_all로 세션 Identity Map 비우기(E1).
UPSERT_CHUNK_SIZE = 50

# 상세 페이지 병렬 수집 시 최대 워커 수 (rate limit은 메인 스레드에서만 적용).
COLLECT_PAYLOADS_MAX_WORKERS = 5
# 동기 수집 시 동시에 유지할 Future 상한. O(N) 메모리 방지.
COLLECT_IN_FLIGHT_LIMIT = 500
# 비동기 수집 시 전체 동시 요청 수. 호스트별 delay는 유지.
COLLECT_ASYNC_CONCURRENCY = 10

# Bounded Seen Set: 최대 보유 개수. 초과 시 가장 오래된 항목 evict. OOM 방지.
CRAWL_SEEN_MAX_SIZE = 10_000

# 비동기 재시도: Exponential Backoff + Jitter. Thundering Herd 방지.
CRAWL_RETRY_BASE_SEC = 1.0
CRAWL_RETRY_MAX_SEC = 60.0
CRAWL_RETRY_JITTER_SEC = 1.0
CRAWL_RETRY_MAX_ATTEMPTS = 5


class _BoundedSeenSet:
    """최대 max_size개 external_id만 유지. 초과 시 가장 오래된 항목 evict. O(1) add/contains."""

    __slots__ = ("_deque", "_set", "_max_size")

    def __init__(self, max_size: int = CRAWL_SEEN_MAX_SIZE) -> None:
        self._deque: deque[str] = deque()
        self._set: set[str] = set()
        self._max_size = max_size

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


async def crawl_college(session: AsyncSession, college_code: str) -> int:
    """
    단과대 1개 크롤 (완전 비동기). httpx.AsyncClient + get_*_links_async / scrape_*_detail_async.
    asyncio.to_thread 제거. 반환: upsert한 공지 개수.
    """
    college = await get_college_by_external_id(session, college_code)
    if not college:
        raise ValueError(f"College not found: {college_code}")

    module_name = COLLEGE_CODE_TO_MODULE.get(college_code)
    if not module_name:
        raise ValueError(f"No crawler module for college: {college_code}")

    config = CRAWLER_CONFIG.get(module_name)
    if not config or not config.get("url"):
        raise ValueError(f"No crawler config or url for: {module_name}")

    list_url = config["url"]
    get_links_async_fn, scrape_async_fn = get_crawler_async(module_name)
    seen: set[str] = set()

    async with httpx.AsyncClient(timeout=CRAWL_PAGE_TIMEOUT_SECONDS) as client:
        links = await get_links_async_fn(client, list_url)

        if not links:
            return 0

        total_count = 0
        chunk: list[dict] = []
        async for payload in _collect_payloads_async(
            client, links, college.id, scrape_async_fn, POLITE_DELAY_SECONDS, seen
        ):
            chunk.append(payload)
            if len(chunk) >= UPSERT_CHUNK_SIZE:
                ids = await upsert_notices_bulk(session, chunk)
                total_count += len(ids)
                chunk.clear()
        if chunk:
            ids = await upsert_notices_bulk(session, chunk)
            total_count += len(ids)
    return total_count


def _scrape_one_sync(
    post: dict, scrape_fn: Callable
) -> tuple[dict, str, ScrapeResult | None, BaseException | None]:
    """워커용: scrape_fn(detail_url) 호출. (post, detail_url, data, exc) 반환. data는 ScrapeResult 또는 None."""
    detail_url = post.get("url") or ""
    try:
        data = scrape_fn(detail_url)
        return (post, detail_url, data, None)
    except BaseException as e:
        return (post, detail_url, None, e)


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
) -> tuple[dict, str, ScrapeResult | None, BaseException | None]:
    """한 건 비동기 스크랩. 모듈 레벨로 분리해 단위 테스트 가능."""
    async with sem:
        detail_url = post.get("url") or ""
        await rate_limiter.wait_async(host_from_url(detail_url) or "_")
        try:
            data = await scrape_async_fn(client, detail_url)
            return (post, detail_url, data, None)
        except BaseException as e:
            return (post, detail_url, None, e)


def _process_scrape_result(
    post: dict,
    detail_url: str,
    data: ScrapeResult | None,
    exc: BaseException | None,
    college_id: uuid.UUID,
    seen: set[str] | _BoundedSeenSet,
    tracker: CrawlErrorTracker,
) -> tuple[dict | None, CrawlThresholdExceeded | BaseException | None]:
    """
    한 건 스크랩 결과 처리. CrawlErrorTracker로 상태 캡슐화. sync/async 공통.
    반환: (payload 또는 None, raise할 예외 또는 None).
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
        if isinstance(exc, (ValueError, KeyError, AttributeError, TypeError)):
            logger.warning(
                "scrape failed (parser): url=%s error=%s",
                detail_url[:200] if detail_url else "",
                exc,
                exc_info=True,
            )
            threshold_exc = tracker.record_parser_failure()
            return (None, threshold_exc)
        return (None, exc)
    tracker.record_success()
    title, date_str, html_content = data.title, data.date_str, data.html_content
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


def _collect_payloads_sync(
    links: list[dict],
    college_id: uuid.UUID,
    scrape_fn: Callable,
    delay_sec: float,
    seen: set[str] | _BoundedSeenSet | None = None,
) -> Iterator[dict]:
    """
    동기: Bounded in-flight(K)로 링크 처리. delay → scrape_fn 병렬 → build_notice_payload → 중복 제거.
    O(K) 메모리. 파서/구조 예외는 임계치 초과 시 CrawlThresholdExceeded raise.
    """
    if seen is None:
        seen = set()
    rate_limiter = get_host_rate_limiter_sync(delay_sec)
    tracker = CrawlErrorTracker()
    remaining = deque(links)

    try:
        with ThreadPoolExecutor(max_workers=COLLECT_PAYLOADS_MAX_WORKERS) as executor:
            futures: dict = {}
            for _ in range(min(COLLECT_IN_FLIGHT_LIMIT, len(remaining))):
                if not remaining:
                    break
                post = remaining.popleft()
                rate_limiter.wait_sync(host_from_url(post.get("url") or "") or "_")
                fut = executor.submit(_scrape_one_sync, post, scrape_fn)
                futures[fut] = post

            while futures:
                done, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)
                for fut in done:
                    post = futures.pop(fut)
                    try:
                        p, detail_url, data, exc = fut.result()
                    except Exception as e:
                        logger.warning("scrape future exception: %s", e, exc_info=True)
                        if remaining:
                            next_post = remaining.popleft()
                            rate_limiter.wait_sync(
                                host_from_url(next_post.get("url") or "") or "_"
                            )
                            futures[executor.submit(_scrape_one_sync, next_post, scrape_fn)] = next_post
                        continue
                    payload, raise_exc = _process_scrape_result(
                        post, detail_url, data, exc, college_id, seen, tracker
                    )
                    if raise_exc is not None:
                        raise raise_exc
                    if payload is not None:
                        yield payload
                    if remaining:
                        next_post = remaining.popleft()
                        rate_limiter.wait_sync(
                            host_from_url(next_post.get("url") or "") or "_"
                        )
                        futures[executor.submit(_scrape_one_sync, next_post, scrape_fn)] = next_post
    finally:
        close_fn = getattr(rate_limiter, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                # 종료 실패는 치명적이지 않으므로 무시
                pass


async def _collect_payloads_async(
    client: httpx.AsyncClient,
    links: list[dict],
    college_id: uuid.UUID,
    scrape_async_fn,
    delay_sec: float,
    seen: set[str] | _BoundedSeenSet | None = None,
):
    """
    비동기: Semaphore(W) + 호스트별 delay로 제한된 병렬 수집. 1 req/s 직렬 완화.
    파서/구조 예외는 임계치 초과 시 CrawlThresholdExceeded raise.
    """
    if seen is None:
        seen = set()
    rate_limiter = get_host_rate_limiter_async(delay_sec)
    sem = asyncio.Semaphore(COLLECT_ASYNC_CONCURRENCY)
    tracker = CrawlErrorTracker()
    remaining = deque(links)
    post_retries: dict[str, int] = {}  # url -> retry count (Exponential Backoff + Jitter)

    def _task(post: dict) -> asyncio.Task:
        return asyncio.create_task(
            _fetch_one_async(client, post, scrape_async_fn, rate_limiter, sem)
        )

    pending: set[asyncio.Task] = set()
    for _ in range(min(COLLECT_ASYNC_CONCURRENCY, len(remaining))):
        if not remaining:
            break
        pending.add(_task(remaining.popleft()))

    try:
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                try:
                    post, detail_url, data, exc = task.result()
                except Exception as e:
                    logger.warning("scrape task exception: %s", e, exc_info=True)
                    if remaining:
                        pending.add(_task(remaining.popleft()))
                    continue
                if exc is not None and isinstance(exc, _NETWORK_EXC_TYPES):
                    tracker.record_attempt()
                    logger.warning(
                        "scrape failed (network/timeout): url=%s error=%s",
                        detail_url[:200] if detail_url else "",
                        exc,
                        exc_info=True,
                    )
                    tracker.record_network_or_skip()
                    retry_count = post_retries.get(detail_url, 0) + 1
                    post_retries[detail_url] = retry_count
                    if retry_count <= CRAWL_RETRY_MAX_ATTEMPTS:
                        backoff = min(
                            CRAWL_RETRY_BASE_SEC * (2 ** (retry_count - 1))
                            + random.uniform(0, CRAWL_RETRY_JITTER_SEC),
                            CRAWL_RETRY_MAX_SEC,
                        )
                        await asyncio.sleep(backoff)
                        pending.add(_task(post))
                    elif remaining:
                        pending.add(_task(remaining.popleft()))
                    continue
                payload, raise_exc = _process_scrape_result(
                    post, detail_url, data, exc, college_id, seen, tracker
                )
                if raise_exc is not None:
                    raise raise_exc
                post_retries.pop(post.get("url") or "", None)
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


def crawl_college_sync(
    session: Session,
    college_code: str,
    *,
    on_chunk_processed: Callable[[list[uuid.UUID]], None] | None = None,
) -> tuple[int, list[uuid.UUID]]:
    """
    단과대 1개 크롤 (동기, Celery 워커 전용). 동기 DB 세션·Repository 사용.
    get_*_links / (1초 sleep) / scrape_*_detail → upsert_notice_sync.
    content_hash가 바뀌었거나 신규 공지는 4단계 AI 큐 대상.
    on_chunk_processed: 청크 upsert 직후 호출(메모리 누적 없이 즉시 enqueue용). None이면 notice_id 목록 반환.
    반환: (upsert한 개수, AI 처리 대상 notice_id 목록). on_chunk_processed 사용 시 목록은 [].
    트랜잭션 경계: 호출자(run_crawl_job_sync 등)가 세션을 소유. 이 함수는 전달받은 세션으로 Repository만 호출.
    """
    college = get_college_by_external_id_sync(session, college_code)
    if not college:
        raise ValueError(f"College not found: {college_code}")

    module_name = COLLEGE_CODE_TO_MODULE.get(college_code)
    if not module_name:
        raise ValueError(f"No crawler module for college: {college_code}")

    config = CRAWLER_CONFIG.get(module_name)
    if not config or not config.get("url"):
        raise ValueError(f"No crawler config or url for: {module_name}")

    list_url = config["url"]
    get_links_fn, scrape_fn = get_crawler(module_name)
    links = get_links_fn(list_url)
    if not links:
        return (0, [])

    seen = _BoundedSeenSet(CRAWL_SEEN_MAX_SIZE)
    notice_ids_to_process: list[uuid.UUID] = []
    total_upserted = 0
    chunk: list[dict] = []
    for payload in _collect_payloads_sync(
        links, college.id, scrape_fn, POLITE_DELAY_SECONDS, seen
    ):
        chunk.append(payload)
        if len(chunk) >= UPSERT_CHUNK_SIZE:
            ids = upsert_notices_bulk_sync(session, chunk)
            total_upserted += len(ids)
            notice_ids_to_process.extend(ids)
            chunk.clear()
    if chunk:
        ids = upsert_notices_bulk_sync(session, chunk)
        total_upserted += len(ids)
        notice_ids_to_process.extend(ids)
    # 커밋 후 한 번에 enqueue (AI 워커가 notice 조회 전에 커밋이 보이도록)
    if on_chunk_processed is not None:
        session.commit()
        session.expunge_all()
        on_chunk_processed(notice_ids_to_process)
        return (total_upserted, [])
    return (total_upserted, notice_ids_to_process)


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
    from datetime import UTC, datetime

    college = get_college_by_external_id_sync(session, college_code)
    if not college:
        raise ValueError(f"College not found: {college_code}")
    run_id = ensure_crawl_run_task_sync(session, task_id)
    create_or_update_crawl_run_sync(session, run_id, college.id)
    session.commit()
    try:
        count, _ = crawl_college_sync(
            session, college_code, on_chunk_processed=on_chunk_processed
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
        update_crawl_run_sync(
            session,
            run_id,
            finished_at=datetime.now(UTC),
            status=CrawlRunStatus.FAILED.value,
            error_message=(str(e))[:2000],
        )
        session.commit()
        raise
