"""
크롤 디스패처/서비스: config → get_*_links / scrape_*_detail, 1초 딜레이, external_id·content_hash → Repository.
HTTP 미의존. 비동기(웹)·동기(워커) 세션 모두 지원.
"""

import asyncio
import hashlib
import logging
import re
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse, urlunparse

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
    CrawlThresholdExceeded,
    PARSER_CONSECUTIVE_FAILURES_THRESHOLD,
    PARSER_FAILURE_RATIO_THRESHOLD,
)
from app.core.crawler_config import COLLEGE_CODE_TO_MODULE, CRAWLER_CONFIG, get_crawler, get_crawler_async
from app.core.storage import upload_notice_html
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

# 본문 HTML 최대 바이트. 초과 시 해당 공지 스킵(OOM 방지).
MAX_HTML_BYTES = 5 * 1024 * 1024

# sync 경로 청크 단위 upsert 크기. commit 후 expunge_all로 세션 Identity Map 비우기(E1).
UPSERT_CHUNK_SIZE = 50

# 상세 페이지 병렬 수집 시 최대 워커 수 (rate limit은 메인 스레드에서만 적용).
COLLECT_PAYLOADS_MAX_WORKERS = 5
# 동기 수집 시 동시에 유지할 Future 상한. O(N) 메모리 방지.
COLLECT_IN_FLIGHT_LIMIT = 500
# 비동기 수집 시 전체 동시 요청 수. 호스트별 delay는 유지.
COLLECT_ASYNC_CONCURRENCY = 10


def _normalize_url_for_hash(url: str) -> str:
    """쿼리 스트링 노이즈(utm, session 등) 제거 후 URL 재조립. 동일 공지가 서로 다른 URL로 무한 적재되는 것 방지."""
    try:
        p = urlparse(url)
        q = parse_qs(p.query, keep_blank_values=False)
        noise_prefixes = ("utm_", "fbclid", "gclid", "session", "sid", "from", "ref")
        filtered = {k: v for k, v in q.items() if not any(k.lower().startswith(prefix) for prefix in noise_prefixes)}
        new_query = "&".join(f"{k}={v[0]}" for k, v in sorted(filtered.items()) if v)
        return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, ""))
    except (ValueError, AttributeError):
        return url


def _url_path_only_for_hash(url: str) -> str:
    """해시 fallback용: 쿼리 제거, path만 사용. 세션/추적 파라미터로 동일 공지가 중복 저장되는 것 방지."""
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except (ValueError, AttributeError):
        return url or ""


def _external_id_from_url(url: str) -> str:
    """URL에서 external_id 추출 (no가 없을 때 사용). path 또는 articleNo 등. 해시 fallback 시 path만 사용."""
    try:
        p = urlparse(url)
        q = parse_qs(p.query)
        # ★ "idx" 추가: 경영대 등 고유번호 파라미터 대응
        for key in ("articleNo", "article_no", "no", "id", "idx"):
            if q.get(key):
                return str(q[key][0])
        segment = p.path.rstrip("/").split("/")[-1]
        if segment and segment.isalnum():
            return segment
        path_only = _url_path_only_for_hash(url)
        return hashlib.sha256(path_only.encode()).hexdigest()[:32]
    except (ValueError, KeyError, AttributeError, IndexError) as e:
        logger.warning(
            "_external_id_from_url fallback to hash: url=%s error=%s",
            url[:200] if url else "",
            e,
        )
        try:
            import sentry_sdk

            sentry_sdk.capture_exception(e)
        except (OSError, URLError) as sentry_err:
            logger.warning("Sentry capture_exception failed: %s", sentry_err)
        path_only = _url_path_only_for_hash(url)
        return hashlib.sha256(path_only.encode()).hexdigest()[:32]


def _content_hash_from_title_and_html(
    title: str,
    content_html: str | None,
    body_text: str | None = None,
) -> str:
    """제목 + 순수 본문 텍스트만으로 sha256. body_text가 있으면 파싱 생략."""
    if body_text is not None:
        text_for_hash = body_text
    else:
        text_for_hash = ""
        if content_html:
            soup = BeautifulSoup(content_html, "html.parser")
            text_for_hash = soup.get_text(separator="\n", strip=True)
    raw = f"{title}\n{text_for_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_published_at(date_str: str | None) -> datetime | None:
    """YYYY.MM.DD 등 문자열을 timezone-aware datetime으로. 실패 시 None. 파싱 실패 시 Sentry 전송 의무."""
    if not date_str:
        return None
    try:
        match = re.search(r"(\d{4})[.-](\d{1,2})[.-](\d{1,2})", date_str)
        if match:
            y, m, d = match.groups()
            return datetime(int(y), int(m), int(d), tzinfo=UTC)
        logger.warning(
            "_parse_published_at no match (format change?): date_str=%r",
            date_str[:100] if date_str else None,
        )
        try:
            import sentry_sdk

            sentry_sdk.capture_message(
                f"_parse_published_at no match (format change?): date_str={date_str[:100]!r}",
                level="warning",
            )
        except (OSError, URLError) as sentry_err:
            logger.warning("Sentry capture_message failed: %s", sentry_err)
    except (ValueError, AttributeError, TypeError) as e:
        logger.warning(
            "_parse_published_at failed: date_str=%r error=%s",
            date_str[:100] if date_str else None,
            e,
            exc_info=True,
        )
        try:
            import sentry_sdk

            sentry_sdk.capture_exception(e)
        except (OSError, URLError) as sentry_err:
            logger.warning("Sentry capture_exception failed: %s", sentry_err)
    return None


def _attachments_to_dicts(attachments: list) -> list[dict]:
    """크롤러 반환(문자열 리스트 또는 이미 dict) → Notice.attachments 형식."""
    if not attachments:
        return []
    out = []
    for a in attachments:
        if isinstance(a, dict):
            out.append(a)
        else:
            out.append({"name": str(a)})
    return out


def build_notice_payload(
    college_id: uuid.UUID,
    post: dict,
    detail_url: str,
    title: str,
    date_str: str | None,
    html_content: str | None,
    images: list | None,
    attachments: list | None,
    body_text_for_hash: str | None = None,
    external_id: str | None = None,
) -> dict | None:
    """
    한 건 공지 스크랩 결과 → upsert용 payload dict. 스킵 시 None(로깅 후 반환).
    순수 함수: HTTP/DB 미의존. crawl_college / crawl_college_sync 공통.
    body_text_for_hash가 있으면 해시 계산 시 HTML 재파싱 생략.
    """
    if not title:
        return None
    content_bytes = (html_content or "").encode("utf-8")
    if len(content_bytes) > MAX_HTML_BYTES:
        logger.warning(
            "build_notice_payload skipped (HTML too large): url=%s size=%d max=%d",
            detail_url[:200] if detail_url else "",
            len(content_bytes),
            MAX_HTML_BYTES,
        )
        return None
    title_stripped = (title or "").strip()
    if title_stripped in ("제목 없음", "(본문 영역을 찾을 수 없습니다)", ""):
        logger.warning(
            "build_notice_payload skipped (placeholder title): url=%s title=%r",
            detail_url[:200] if detail_url else "",
            title[:80] if title else "",
        )
        return None
    external_id_value = external_id or post.get("no") or _external_id_from_url(detail_url)
    content_hash = _content_hash_from_title_and_html(
        title, html_content, body_text_for_hash
    )
    published_at = _parse_published_at(date_str)
    att_dicts = _attachments_to_dicts(attachments or [])
    content_url = upload_notice_html(
        html_content,
        college_id=college_id,
        external_id=external_id_value,
        content_hash=content_hash,
    )
    return {
        "college_id": college_id,
        "external_id": external_id_value,
        "title": title,
        "url": detail_url or None,
        "content_url": content_url,
        "images": images,
        "attachments": att_dicts,
        "content_hash": content_hash,
        "published_at": published_at,
    }


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
) -> tuple[dict, str, tuple | None, BaseException | None]:
    """워커용: scrape_fn(detail_url) 호출. (post, detail_url, data, exc) 반환. data는 (title, date_str, html_content, images, attachments) 또는 None."""
    detail_url = post.get("url") or ""
    try:
        data = scrape_fn(detail_url)
        return (post, detail_url, data, None)
    except BaseException as e:
        return (post, detail_url, None, e)


def _collect_payloads_sync(
    links: list[dict],
    college_id: uuid.UUID,
    scrape_fn: Callable,
    delay_sec: float,
    seen: set[str] | None = None,
) -> Iterator[dict]:
    """
    동기: Bounded in-flight(K)로 링크 처리. delay → scrape_fn 병렬 → build_notice_payload → 중복 제거.
    O(K) 메모리. 파서/구조 예외는 임계치 초과 시 CrawlThresholdExceeded raise.
    """
    if seen is None:
        seen = set()
    rate_limiter = get_host_rate_limiter_sync(delay_sec)
    attempted = 0
    parser_failures = 0
    consecutive_parser_failures = 0
    remaining = deque(links)

    def process_result(post: dict, detail_url: str, data: tuple | None, exc: BaseException | None) -> dict | None:
        nonlocal attempted, parser_failures, consecutive_parser_failures
        attempted += 1
        if exc is not None:
            if isinstance(
                exc, (TimeoutError, OSError, ConnectionError, RequestException)
            ):
                logger.warning(
                    "scrape failed (timeout/network): url=%s error=%s",
                    detail_url[:200] if detail_url else "", exc, exc_info=True,
                )
                consecutive_parser_failures = 0
                return None
            if isinstance(exc, HtmlTooLargeError):
                logger.warning(
                    "scrape skipped (body too large): url=%s %s",
                    detail_url[:200] if detail_url else "", exc,
                )
                consecutive_parser_failures = 0
                return None
            if isinstance(exc, (ValueError, KeyError, AttributeError, TypeError)):
                logger.warning(
                    "scrape failed (parser): url=%s error=%s",
                    detail_url[:200] if detail_url else "", exc, exc_info=True,
                )
                parser_failures += 1
                consecutive_parser_failures += 1
                if consecutive_parser_failures >= PARSER_CONSECUTIVE_FAILURES_THRESHOLD:
                    raise CrawlThresholdExceeded(
                        f"consecutive parser failures {consecutive_parser_failures} >= {PARSER_CONSECUTIVE_FAILURES_THRESHOLD}",
                        attempted=attempted,
                        parser_failures=parser_failures,
                        consecutive=consecutive_parser_failures,
                    )
                if attempted >= 3 and (parser_failures / attempted) > PARSER_FAILURE_RATIO_THRESHOLD:
                    raise CrawlThresholdExceeded(
                        f"parser failure ratio {parser_failures}/{attempted} > {PARSER_FAILURE_RATIO_THRESHOLD}",
                        attempted=attempted,
                        parser_failures=parser_failures,
                        consecutive=consecutive_parser_failures,
                    )
                return None
            raise exc
        consecutive_parser_failures = 0
        title, date_str, html_content, images, attachments = data
        # dedupe를 위해 external_id를 먼저 계산해 중복이면 HTML 업로드 자체를 건너뛴다.
        external_id = post.get("no") or _external_id_from_url(detail_url)
        if external_id in seen:
            return None
        body_text_for_hash = (
            BeautifulSoup(html_content, "html.parser").get_text(separator="\n", strip=True)
            if html_content else ""
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
            return None
        seen.add(external_id)
        return payload

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
                    try:
                        payload = process_result(post, detail_url, data, exc)
                    except CrawlThresholdExceeded:
                        raise
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
    seen: set[str] | None = None,
):
    """
    비동기: Semaphore(W) + 호스트별 delay로 제한된 병렬 수집. 1 req/s 직렬 완화.
    파서/구조 예외는 임계치 초과 시 CrawlThresholdExceeded raise.
    """
    if seen is None:
        seen = set()
    rate_limiter = get_host_rate_limiter_async(delay_sec)
    sem = asyncio.Semaphore(COLLECT_ASYNC_CONCURRENCY)
    attempted = 0
    parser_failures = 0
    consecutive_parser_failures = 0
    remaining = deque(links)

    async def fetch_one(post: dict) -> tuple[dict, str, tuple | None, BaseException | None]:
        async with sem:
            detail_url = post.get("url") or ""
            await rate_limiter.wait_async(host_from_url(detail_url) or "_")
            try:
                data = await scrape_async_fn(client, detail_url)
                return (post, detail_url, data, None)
            except BaseException as e:
                return (post, detail_url, None, e)

    pending: set[asyncio.Task] = set()
    for _ in range(min(COLLECT_ASYNC_CONCURRENCY, len(remaining))):
        if not remaining:
            break
        t = asyncio.create_task(fetch_one(remaining.popleft()))
        pending.add(t)

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
                        pending.add(
                            asyncio.create_task(fetch_one(remaining.popleft()))
                        )
                    continue
                attempted += 1
                if exc is not None:
                    if isinstance(
                        exc,
                        (
                            httpx.HTTPError,
                            httpx.TimeoutException,
                            TimeoutError,
                            OSError,
                            ConnectionError,
                        ),
                    ):
                        logger.warning(
                            "scrape failed (network/timeout): url=%s error=%s",
                            detail_url[:200] if detail_url else "",
                            exc,
                            exc_info=True,
                        )
                        consecutive_parser_failures = 0
                    elif isinstance(exc, HtmlTooLargeError):
                        logger.warning(
                            "scrape skipped (body too large): url=%s %s",
                            detail_url[:200] if detail_url else "",
                            exc,
                        )
                        consecutive_parser_failures = 0
                    elif isinstance(
                        exc, (ValueError, KeyError, AttributeError, TypeError)
                    ):
                        parser_failures += 1
                        consecutive_parser_failures += 1
                        logger.warning(
                            "scrape failed (parser): url=%s error=%s",
                            detail_url[:200] if detail_url else "",
                            exc,
                            exc_info=True,
                        )
                        if (
                            consecutive_parser_failures
                            >= PARSER_CONSECUTIVE_FAILURES_THRESHOLD
                        ):
                            raise CrawlThresholdExceeded(
                                f"consecutive parser failures {consecutive_parser_failures} >= {PARSER_CONSECUTIVE_FAILURES_THRESHOLD}",
                                attempted=attempted,
                                parser_failures=parser_failures,
                                consecutive=consecutive_parser_failures,
                            )
                        if attempted >= 3 and (
                            parser_failures / attempted
                        ) > PARSER_FAILURE_RATIO_THRESHOLD:
                            raise CrawlThresholdExceeded(
                                f"parser failure ratio {parser_failures}/{attempted} > {PARSER_FAILURE_RATIO_THRESHOLD}",
                                attempted=attempted,
                                parser_failures=parser_failures,
                                consecutive=consecutive_parser_failures,
                            )
                    else:
                        raise exc
                    if remaining:
                        pending.add(
                            asyncio.create_task(fetch_one(remaining.popleft()))
                        )
                    continue
                consecutive_parser_failures = 0
                title, date_str, html_content, images, attachments = data
                # dedupe를 위해 external_id를 먼저 계산해 중복이면 HTML 업로드 자체를 건너뛴다.
                external_id = post.get("no") or _external_id_from_url(detail_url)
                if external_id in seen:
                    if remaining:
                        pending.add(
                            asyncio.create_task(fetch_one(remaining.popleft()))
                        )
                    continue
                body_text_for_hash = (
                    BeautifulSoup(html_content, "html.parser").get_text(
                        separator="\n", strip=True
                    )
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
                if remaining:
                    pending.add(
                        asyncio.create_task(fetch_one(remaining.popleft()))
                    )
                if payload is None:
                    continue
                seen.add(external_id)
                yield payload
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

    seen: set[str] = set()
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
            seen.clear()  # 청크 단위 dedupe만 유지해 O(1) 메모리 상한
    if chunk:
        ids = upsert_notices_bulk_sync(session, chunk)
        total_upserted += len(ids)
        notice_ids_to_process.extend(ids)
        seen.clear()
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
