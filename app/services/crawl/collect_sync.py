"""Sync collect: scrape one, process result, collect payloads (bounded in-flight)."""

import logging
import threading
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import httpx
from requests.exceptions import RequestException
from requests.exceptions import Timeout as RequestsTimeout
from tenacity import RetryError, Retrying, retry_if_exception, stop_after_attempt

from app.core.crawl_rate_limit import get_host_rate_limiter_sync, host_from_url
from app.core.metrics import (
    CRAWL_DROP_TOTAL,
    CRAWL_PARSE_THRESHOLD_TRIGGER_TOTAL,
    CRAWL_RETRY_TOTAL,
    DROP_REASON_DUPLICATE,
    DROP_REASON_PRE_DEDUP,
    RETRY_REASON_5XX,
    RETRY_REASON_429,
    RETRY_REASON_NETWORK,
    RETRY_REASON_TIMEOUT,
    increment,
)
from app.domain.contracts.crawl_contracts import CrawlLogContext, LinkItem, NoticeDraft
from app.services.crawl.error_handling import CrawlErrorAction, CrawlErrorHandler
from app.services.crawl.item_pipeline import DefaultNoticeItemPipeline, RawNoticeItem
from app.services.crawl_payload import _external_id_from_url
from app.services.crawl_policy import (
    HTTP_RETRY_STATUS_CODES,
    HTTP_RETRY_STATUS_MAX_5XX,
    HTTP_RETRY_STATUS_MIN_5XX,
    HTTP_SKIP_STATUS_CODES,
    CrawlErrorTracker,
    CrawlThresholdExceeded,
)
from app.services.crawlers.base import ScrapeResult

from .runtime import (
    CRAWL_RETRY_MAX_ATTEMPTS,
    _BoundedSeenSet,
    _RedisSeenSet,
    get_crawl_retry_wait,
)

logger = logging.getLogger(__name__)
_error_handler = CrawlErrorHandler()


@dataclass(frozen=True, slots=True)
class ScrapeAttemptResult:
    """??嫄??ㅽ겕???쒕룄 寃곌낵. (post, detail_url, data, exc) ?쒗뵆 ????대쫫?쇰줈 ?묎렐."""

    post: LinkItem
    detail_url: str
    data: ScrapeResult | None
    exc: Exception | None


_BASE_NETWORK_EXC_TYPES = (
    TimeoutError,
    OSError,
    ConnectionError,
    RequestException,
    httpx.HTTPError,
    httpx.TimeoutException,
)


def _get_http_status_code(exc: BaseException) -> int | None:
    if hasattr(exc, "response") and exc.response is not None:
        if hasattr(exc.response, "status_code"):
            return int(exc.response.status_code)
    return None


def _is_skippable(exc: BaseException) -> bool:
    code = _get_http_status_code(exc)
    return code in HTTP_SKIP_STATUS_CODES if code is not None else False


def _is_retryable(exc: BaseException) -> bool:
    code = _get_http_status_code(exc)
    if code is not None:
        if code in HTTP_SKIP_STATUS_CODES:
            return False
        if code in HTTP_RETRY_STATUS_CODES or HTTP_RETRY_STATUS_MIN_5XX <= code <= HTTP_RETRY_STATUS_MAX_5XX:
            return True
        return False
    return isinstance(exc, _BASE_NETWORK_EXC_TYPES)


def _retry_reason_from_exc(exc: BaseException) -> str:
    """?ъ떆??硫뷀듃由?슜 reason ?쇰꺼 (怨좎젙 enum)."""
    code = _get_http_status_code(exc)
    if code == 429:
        return RETRY_REASON_429
    if code is not None and HTTP_RETRY_STATUS_MIN_5XX <= code <= HTTP_RETRY_STATUS_MAX_5XX:
        return RETRY_REASON_5XX
    if isinstance(exc, TimeoutError | httpx.TimeoutException | RequestsTimeout):
        return RETRY_REASON_TIMEOUT
    return RETRY_REASON_NETWORK


def _scrape_one_sync(post: LinkItem, scrape_fn: Callable) -> ScrapeAttemptResult:
    """?뚯빱?? scrape_fn(detail_url) ?몄텧. data??ScrapeResult ?먮뒗 None."""
    detail_url = post.get("url") or ""
    try:
        data = scrape_fn(detail_url)
        return ScrapeAttemptResult(post=post, detail_url=detail_url, data=data, exc=None)
    except Exception as e:
        return ScrapeAttemptResult(post=post, detail_url=detail_url, data=None, exc=e)


def _resolve_external_id(post: LinkItem, detail_url: str) -> str | None:
    """post? detail_url?먯꽌 external_id 異붿텧. ?④퀎 2쨌3쨌4 怨듯넻."""
    return post.get("no") or _external_id_from_url(detail_url) or None


def _apply_exception_policy(
    post: LinkItem,
    detail_url: str,
    exc: Exception | None,
    data: ScrapeResult | None,
    tracker: CrawlErrorTracker,
    ctx: CrawlLogContext,
) -> tuple[str, CrawlThresholdExceeded | Exception | None]:
    """
    ?④퀎 1: ?덉쇅 遺꾨쪟쨌?쒕∼ ?먮떒. CrawlErrorTracker ?몄텧.
    諛섑솚: ("drop", None) | ("raise", exc) | ("ok", None). "ok"?대㈃ data媛 ?덉쓬??蹂댁옣??
    """
    tracker.record_attempt()
    eid = _resolve_external_id(post, detail_url)
    if exc is not None:
        handled = _error_handler.handle(
            exc,
            detail_url=detail_url,
            ctx=ctx,
            external_id=eid,
        )
        if handled.action == CrawlErrorAction.DROP:
            tracker.record_network_or_skip()
            if handled.drop_reason:
                increment(CRAWL_DROP_TOTAL, 1, labels={"reason": handled.drop_reason})
            return ("drop", None)
        if handled.action == CrawlErrorAction.PARSER:
            threshold_exc = tracker.record_parser_failure()
            return ("raise", threshold_exc)
        return ("raise", exc)
    assert data is not None
    tracker.record_success()
    return ("ok", None)


def _process_scrape_result(
    post: LinkItem,
    detail_url: str,
    data: ScrapeResult | None,
    exc: Exception | None,
    college_id: uuid.UUID,
    seen: set[str] | _BoundedSeenSet | _RedisSeenSet,
    tracker: CrawlErrorTracker,
    ctx: CrawlLogContext,
) -> tuple[NoticeDraft | None, CrawlThresholdExceeded | Exception | None]:
    """
    ??嫄??ㅽ겕??寃곌낵 泥섎━. ?④퀎: ?덉쇅 ?뺤콉 ??以묐났 泥댄겕 ??payload 鍮뚮뱶 ??seen ?깅줉.
    諛섑솚: (NoticeDraft ?먮뒗 None, raise???덉쇅 ?먮뒗 None).
    """
    action, raise_exc = _apply_exception_policy(post, detail_url, exc, data, tracker, ctx)
    if action == "drop":
        return (None, None)
    if action == "raise":
        if isinstance(raise_exc, CrawlThresholdExceeded):
            increment(CRAWL_PARSE_THRESHOLD_TRIGGER_TOTAL, 1)
        return (None, raise_exc)
    assert data is not None
    external_id = _resolve_external_id(post, detail_url)
    if external_id is not None and external_id in seen:
        increment(CRAWL_DROP_TOTAL, 1, labels={"reason": DROP_REASON_DUPLICATE})
        return (None, None)
    pipeline = DefaultNoticeItemPipeline(seen)
    payload = pipeline.process(
        RawNoticeItem(
            college_id=college_id,
            post=post,
            detail_url=detail_url,
            data=data,
        ),
        ctx,
    )
    if payload is None:
        return (None, None)
    return (payload, None)


def _execute_scrape_with_retry(
    post: LinkItem,
    scrape_fn: Callable,
    rate_limiter: Any,
) -> ScrapeAttemptResult:
    """
    ?ъ떆??+ rate limit(留??쒕룄 ?? + ?덉쇅 ?뺤콉 ?곸슜. Semaphore ?몃?.
    ?몄텧泥? _scrape_one_sync_with_sem (?숈떆?깆? 洹몄そ?먯꽌留??좎?).
    """
    detail_url = post.get("url") or ""
    host = host_from_url(detail_url) or "_"
    last_result: ScrapeAttemptResult | None = None
    try:
        for attempt in Retrying(
            stop=stop_after_attempt(CRAWL_RETRY_MAX_ATTEMPTS),
            wait=get_crawl_retry_wait,
            retry=retry_if_exception(_is_retryable),
            reraise=False,
        ):
            with attempt:
                rate_limiter.wait_sync(host)
                last_result = _scrape_one_sync(post, scrape_fn)
                if last_result.exc is None:
                    return last_result
                if _is_skippable(last_result.exc):
                    return last_result
                if _is_retryable(last_result.exc):
                    increment(
                        CRAWL_RETRY_TOTAL,
                        1,
                        labels={"reason": _retry_reason_from_exc(last_result.exc)},
                    )
                    raise last_result.exc
                return last_result
    except RetryError:
        pass
    if last_result is not None:
        return last_result
    return ScrapeAttemptResult(post=post, detail_url=detail_url, data=None, exc=None)


def _scrape_one_sync_with_sem(
    post: LinkItem,
    scrape_fn: Callable,
    rate_limiter: Any,
    sem: threading.BoundedSemaphore,
) -> ScrapeAttemptResult:
    """BoundedSemaphore濡??숈떆 ?ㅽ겕?????쒗븳. ?뚯빱 ?ㅻ젅?쒖뿉???몄텧."""
    sem.acquire()
    try:
        return _execute_scrape_with_retry(post, scrape_fn, rate_limiter)
    finally:
        sem.release()


def _collect_payloads_sync(
    links: list[LinkItem],
    college_id: uuid.UUID,
    scrape_fn: Callable,
    delay_sec: float,
    *,
    max_workers: int,
    in_flight_limit: int,
    seen: set[str] | _BoundedSeenSet | _RedisSeenSet | None = None,
    ctx: CrawlLogContext,
) -> Iterator[NoticeDraft]:
    """
    ?숆린: Bounded in-flight(K)濡?留곹겕 泥섎━. Semaphore + as_completed濡??쒖뼱 ?⑥닚??
    O(K) 硫붾え由? ?뚯꽌/援ъ“ ?덉쇅???꾧퀎移?珥덇낵 ??CrawlThresholdExceeded raise.
    """
    seen_for_dedup: set[str] | _BoundedSeenSet | _RedisSeenSet = (
        seen if seen is not None else set()
    )
    rate_limiter = get_host_rate_limiter_sync(delay_sec)
    tracker = CrawlErrorTracker()
    remaining = deque(links)
    sem = threading.BoundedSemaphore(in_flight_limit)
    in_flight_external_ids: set[str] = set()

    def submit_one() -> None:
        while remaining:
            post = remaining.popleft()
            no = post.get("no")
            if no is not None and no != "":
                if no in seen_for_dedup or no in in_flight_external_ids:
                    increment(CRAWL_DROP_TOTAL, 1, labels={"reason": DROP_REASON_PRE_DEDUP})
                    continue
            if no is not None and no != "":
                in_flight_external_ids.add(no)
            fut = executor.submit(_scrape_one_sync_with_sem, post, scrape_fn, rate_limiter, sem)
            futures[fut] = post
            return

    executor = ThreadPoolExecutor(max_workers=max_workers)
    futures: dict = {}
    try:
        for _ in range(min(in_flight_limit, len(remaining))):
            if not remaining:
                break
            submit_one()

        while futures:
            for fut in as_completed(set(futures.keys())):
                post = futures.pop(fut)
                in_flight_no = post.get("no") if isinstance(post.get("no"), str) else None
                try:
                    result = fut.result()
                except Exception as e:
                    logger.warning("scrape future exception: %s", e, exc_info=True)
                    if in_flight_no:
                        in_flight_external_ids.discard(in_flight_no)
                    submit_one()
                    continue
                try:
                    payload, raise_exc = _process_scrape_result(
                        result.post,
                        result.detail_url,
                        result.data,
                        result.exc,
                        college_id,
                        seen_for_dedup,
                        tracker,
                        ctx,
                    )
                    if raise_exc is not None:
                        raise raise_exc
                    if payload is not None:
                        yield payload
                finally:
                    if in_flight_no:
                        in_flight_external_ids.discard(in_flight_no)
                submit_one()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        close_fn = getattr(rate_limiter, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass



