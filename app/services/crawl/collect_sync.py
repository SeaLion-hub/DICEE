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
from bs4 import BeautifulSoup
from requests.exceptions import RequestException
from tenacity import RetryError, Retrying, retry_if_exception, stop_after_attempt

from app.core.crawl_http import HtmlTooLargeError
from app.core.crawl_rate_limit import get_host_rate_limiter_sync, host_from_url
from app.domain.contracts.crawl_contracts import CrawlLogContext, LinkItem, NoticeDraft
from app.services.crawl_payload import _external_id_from_url, build_notice_payload
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
    _crawl_retry_wait,
    _RedisSeenSet,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScrapeAttemptResult:
    """한 건 스크랩 시도 결과. (post, detail_url, data, exc) 튜플 대신 이름으로 접근."""

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


def _is_fatal(exc: BaseException) -> bool:
    code = _get_http_status_code(exc)
    if code is not None:
        skip_or_retry = (
            code in HTTP_SKIP_STATUS_CODES
            or code in HTTP_RETRY_STATUS_CODES
            or (HTTP_RETRY_STATUS_MIN_5XX <= code <= HTTP_RETRY_STATUS_MAX_5XX)
        )
        return not skip_or_retry
    return False


def _scrape_one_sync(post: LinkItem, scrape_fn: Callable) -> ScrapeAttemptResult:
    """워커용: scrape_fn(detail_url) 호출. data는 ScrapeResult 또는 None."""
    detail_url = post.get("url") or ""
    try:
        data = scrape_fn(detail_url)
        return ScrapeAttemptResult(post=post, detail_url=detail_url, data=data, exc=None)
    except Exception as e:
        return ScrapeAttemptResult(post=post, detail_url=detail_url, data=None, exc=e)


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
    한 건 스크랩 결과 처리. CrawlErrorTracker로 상태 캡슐화. sync/async 공통.
    반환: (NoticeDraft 또는 None, raise할 예외 또는 None).
    """
    tracker.record_attempt()
    log_extra = {**ctx.extra_for_log(), "url": detail_url[:200] if detail_url else ""}
    external_id = post.get("no") or _external_id_from_url(detail_url)
    if external_id:
        log_extra["external_id"] = external_id
    if exc is not None:
        if _is_skippable(exc):
            logger.warning(
                "scrape skipped (http %s): url=%s",
                _get_http_status_code(exc),
                detail_url[:200] if detail_url else "",
                extra=log_extra,
            )
            tracker.record_network_or_skip()
            return (None, None)
        if _is_retryable(exc):
            logger.warning(
                "scrape failed (timeout/network/retryable): url=%s error=%s",
                detail_url[:200] if detail_url else "",
                exc,
                exc_info=True,
                extra=log_extra,
            )
            tracker.record_network_or_skip()
            return (None, None)
        if _is_fatal(exc):
            logger.warning(
                "scrape fatal (http %s): url=%s",
                _get_http_status_code(exc),
                detail_url[:200] if detail_url else "",
                extra=log_extra,
            )
            return (None, exc)
        if isinstance(exc, HtmlTooLargeError):
            logger.warning(
                "scrape skipped (body too large): url=%s %s",
                detail_url[:200] if detail_url else "",
                exc,
                extra=log_extra,
            )
            tracker.record_network_or_skip()
            return (None, None)
        if isinstance(exc, ValueError | KeyError | AttributeError | TypeError):
            logger.warning(
                "scrape failed (parser): url=%s error=%s",
                detail_url[:200] if detail_url else "",
                exc,
                exc_info=True,
                extra=log_extra,
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
        BeautifulSoup(html_content, "html.parser").get_text(separator="\n", strip=True) if html_content else ""
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
        ctx=ctx,
    )
    if payload is None:
        return (None, None)
    seen.add(external_id)
    return (payload, None)


def _scrape_one_sync_with_sem(
    post: LinkItem,
    scrape_fn: Callable,
    rate_limiter: Any,
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
                        raise last_result.exc
                    return last_result
        except RetryError:
            pass
        if last_result is not None:
            return last_result
        return ScrapeAttemptResult(post=post, detail_url=detail_url, data=None, exc=None)
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
                    ctx,
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
