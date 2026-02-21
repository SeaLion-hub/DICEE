"""
크롤 디스패처/서비스: config → get_*_links / scrape_*_detail, 1초 딜레이, external_id·content_hash → Repository.
HTTP 미의존. 비동기(웹)·동기(워커) 세션 모두 지원.
"""

import asyncio
import hashlib
import logging
import re
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse, urlunparse

from bs4 import BeautifulSoup
from requests.exceptions import RequestException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import httpx

from app.core.config import settings
from app.core.crawler_config import COLLEGE_CODE_TO_MODULE, CRAWLER_CONFIG, get_crawler, get_crawler_async
from app.repositories.college_repository import (
    get_by_external_id as get_college_by_external_id,
)
from app.repositories.college_repository import (
    get_by_external_id_sync as get_college_by_external_id_sync,
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


def _normalize_url_for_hash(url: str) -> str:
    """쿼리 스트링 노이즈(utm, session 등) 제거 후 URL 재조립. 동일 공지가 서로 다른 URL로 무한 적재되는 것 방지."""
    try:
        p = urlparse(url)
        q = parse_qs(p.query, keep_blank_values=False)
        # 추적/세션 파라미터 제거 (소문자 키 기준)
        noise_prefixes = ("utm_", "fbclid", "gclid", "session", "sid", "from", "ref")
        filtered = {
            k: v for k, v in q.items()
            if not any(k.lower().startswith(prefix) for prefix in noise_prefixes)
        }
        # 쿼리 재구성 (정렬해 일관된 해시)
        new_query = "&".join(
            f"{k}={v[0]}" for k, v in sorted(filtered.items()) if v
        )
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


def _content_hash_from_title_and_html(title: str, content_html: str | None) -> str:
    """제목 + 순수 본문 텍스트(get_text())만으로 sha256."""
    body_text = ""
    if content_html:
        soup = BeautifulSoup(content_html, "html.parser")
        body_text = soup.get_text(separator="\n", strip=True)
    raw = f"{title}\n{body_text}"
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
    college_id: int,
    post: dict,
    detail_url: str,
    title: str,
    date_str: str | None,
    html_content: str | None,
    images: list | None,
    attachments: list | None,
) -> dict | None:
    """
    한 건 공지 스크랩 결과 → upsert용 payload dict. 스킵 시 None(로깅 후 반환).
    순수 함수: HTTP/DB 미의존. crawl_college / crawl_college_sync 공통.
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
    external_id = post.get("no") or _external_id_from_url(detail_url)
    content_hash = _content_hash_from_title_and_html(title, html_content)
    published_at = _parse_published_at(date_str)
    att_dicts = _attachments_to_dicts(attachments or [])
    return {
        "college_id": college_id,
        "external_id": external_id,
        "title": title,
        "url": detail_url or None,
        "raw_html": html_content,
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
        try:
            links = await get_links_async_fn(client, list_url)
        except (httpx.HTTPError, httpx.TimeoutException, TimeoutError, OSError, ConnectionError) as e:
            logger.warning(
                "crawl_college get_links error: college_code=%s list_url=%s error=%s",
                college_code,
                list_url[:200] if list_url else "",
                e,
                exc_info=True,
            )
            return 0

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


def _collect_payloads_sync(
    links: list[dict],
    college_id: int,
    scrape_fn,
    delay_sec: float,
    seen: set[str] | None = None,
) -> Iterator[dict]:
    """
    동기: 링크 순회 → delay → scrape_fn(url) → build_notice_payload → 중복 제거.
    한 건씩 yield하여 메모리 상에 전체 리스트를 쌓지 않음. HTTP/DB 미의존.
    """
    if seen is None:
        seen = set()
    for post in links:
        time.sleep(delay_sec)
        detail_url = post.get("url") or ""
        try:
            title, date_str, html_content, images, attachments = scrape_fn(detail_url)
        except (TimeoutError, OSError, ConnectionError, RequestException) as e:
            logger.warning(
                "scrape failed (timeout/network): url=%s error=%s",
                detail_url[:200] if detail_url else "",
                e,
                exc_info=True,
            )
            continue
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            logger.warning(
                "scrape failed (parser): url=%s error=%s",
                detail_url[:200] if detail_url else "",
                e,
                exc_info=True,
            )
            continue
        payload = build_notice_payload(
            college_id, post, detail_url, title, date_str, html_content, images, attachments
        )
        if payload is None:
            continue
        ext_id = payload["external_id"]
        if ext_id in seen:
            continue
        seen.add(ext_id)
        yield payload


async def _collect_payloads_async(
    client: httpx.AsyncClient,
    links: list[dict],
    college_id: int,
    scrape_async_fn,
    delay_sec: float,
    seen: set[str] | None = None,
):
    """
    비동기: 링크 순회 → await sleep → await scrape_async_fn(client, url) → build_notice_payload → 중복 제거.
    한 건씩 yield하여 메모리 상에 전체 리스트를 쌓지 않음. HTTP/DB 미의존.
    """
    if seen is None:
        seen = set()
    for post in links:
        await asyncio.sleep(delay_sec)
        detail_url = post.get("url") or ""
        try:
            title, date_str, html_content, images, attachments = await scrape_async_fn(
                client, detail_url
            )
        except (httpx.HTTPError, httpx.TimeoutException, TimeoutError, OSError, ConnectionError) as e:
            logger.warning(
                "scrape failed (network/timeout): url=%s error=%s",
                detail_url[:200] if detail_url else "",
                e,
                exc_info=True,
            )
            continue
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            logger.warning(
                "scrape failed (parser): url=%s error=%s",
                detail_url[:200] if detail_url else "",
                e,
                exc_info=True,
            )
            continue
        payload = build_notice_payload(
            college_id, post, detail_url, title, date_str, html_content, images, attachments
        )
        if payload is None:
            continue
        ext_id = payload["external_id"]
        if ext_id in seen:
            continue
        seen.add(ext_id)
        yield payload


def crawl_college_sync(session: Session, college_code: str) -> tuple[int, list[int]]:
    """
    단과대 1개 크롤 (동기, Celery 워커 전용). 동기 DB 세션·Repository 사용.
    get_*_links / (1초 sleep) / scrape_*_detail → upsert_notice_sync.
    content_hash가 바뀌었거나 신규 공지는 4단계 AI 큐 대상이므로 notice_id 목록으로 반환.
    반환: (upsert한 개수, AI 처리 대상 notice_id 목록).
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
    notice_ids_to_process: list[int] = []
    chunk: list[dict] = []
    for payload in _collect_payloads_sync(
        links, college.id, scrape_fn, POLITE_DELAY_SECONDS, seen
    ):
        chunk.append(payload)
        if len(chunk) >= UPSERT_CHUNK_SIZE:
            ids = upsert_notices_bulk_sync(session, chunk)
            session.commit()
            session.expunge_all()
            notice_ids_to_process.extend(ids)
            chunk.clear()
    if chunk:
        ids = upsert_notices_bulk_sync(session, chunk)
        session.commit()
        session.expunge_all()
        notice_ids_to_process.extend(ids)
    return (len(notice_ids_to_process), notice_ids_to_process)
