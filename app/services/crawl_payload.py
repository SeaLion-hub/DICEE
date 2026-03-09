"""
크롤 파싱·페이로드 빌드. 순수 함수 및 스크랩 결과 → Notice upsert용 payload 변환.
HTTP/DB 미의존. crawl_service 오케스트레이터에서 import해 사용.
"""

import base64
import hashlib
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.core.storage import upload_notice_html, upload_notice_image
from app.domain.contracts.crawl_contracts import CrawlLogContext, LinkItem, NoticeDraft

logger = logging.getLogger(__name__)

MAX_HTML_BYTES = 10 * 1024 * 1024  # 본문 HTML 최대 바이트. 초과 시 해당 공지 스킵(OOM 방지).

# Sentry 건별 전송 폭주 방지: 동일 시그니처는 TTL 내 1회만 전송 (디듀프 훅).
_SENTRY_DEDUP_TTL_SECONDS = 60
_sentry_last_sent: dict[str, float] = {}


def _should_send_crawl_sentry(signature: str) -> bool:
    """동일 시그니처에 대해 TTL 내 1회만 True. 호출 시점에 last_sent 갱신."""
    now = time.time()
    if signature in _sentry_last_sent and (now - _sentry_last_sent[signature]) < _SENTRY_DEDUP_TTL_SECONDS:
        return False
    _sentry_last_sent[signature] = now
    return True


def _capture_crawl_sentry_exception(signature: str, exc: BaseException, ctx: CrawlLogContext | None = None) -> None:
    """크롤 파싱: TTL 디듀프 후 capture_exception. ctx로 college_code/run_id/task_id 태그. Fail-open."""
    if not _should_send_crawl_sentry(signature):
        return
    try:
        import sentry_sdk

        if ctx:
            for k, v in ctx.extra_for_log().items():
                if v:
                    sentry_sdk.set_tag(k, v)
        sentry_sdk.capture_exception(exc)
    except (OSError, Exception) as sentry_err:
        logger.warning("Sentry capture_exception failed (fail-open): %s", sentry_err)


_SentryLevel = Literal["fatal", "critical", "error", "warning", "info", "debug"]


def _capture_crawl_sentry_message(
    signature: str,
    message: str,
    level: _SentryLevel = "warning",
    ctx: CrawlLogContext | None = None,
) -> None:
    """크롤 파싱: TTL 디듀프 후 capture_message. ctx로 college_code/run_id/task_id 태그. Fail-open."""
    if not _should_send_crawl_sentry(signature):
        return
    try:
        import sentry_sdk

        if ctx:
            for k, v in ctx.extra_for_log().items():
                if v:
                    sentry_sdk.set_tag(k, v)
        sentry_sdk.capture_message(message, level=level)
    except (OSError, Exception) as sentry_err:
        logger.warning("Sentry capture_message failed (fail-open): %s", sentry_err)


def _url_path_only_for_hash(url: str) -> str:
    """해시 fallback용: 쿼리 제거, path만 사용."""
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except (ValueError, AttributeError):
        return url or ""


def _is_valid_url_scheme(url: str) -> bool:
    """http/https만 허용. 빈 문자열·비정상 scheme 제외."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not url:
        return False
    try:
        p = urlparse(url)
        return (p.scheme or "").lower() in ("http", "https")
    except (ValueError, AttributeError):
        return False


def _filter_valid_urls(items: list[dict]) -> list[dict]:
    """이미지/첨부 dict 목록에서 url·src가 유효한 항목만 유지. 빈 문자열·비정상 scheme 제거."""
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("src") or ""
        if not _is_valid_url_scheme(url):
            continue
        out.append(item)
    return out


def _resolve_notice_images(
    images: list,
    *,
    college_id: uuid.UUID,
    external_id: str,
    ctx: CrawlLogContext | None = None,
) -> list[dict]:
    """
    크롤러 images를 스토리지 URL 기준으로 정규화.
    base64 → 업로드 후 URL; 이미 URL인 항목은 { url, name } 형태로 통일.
    """
    resolved: list[dict] = []
    for idx, item in enumerate(images or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"image_{idx + 1}.jpg").strip() or f"image_{idx + 1}.jpg"
        itype = (item.get("type") or "").strip().lower()
        data = item.get("data")

        if itype == "base64" and data:
            try:
                raw = base64.b64decode(data, validate=True)
            except Exception as e:
                if ctx:
                    logger.debug(
                        "base64 decode failed for image idx=%s: %s",
                        idx,
                        e,
                        extra=ctx.extra_for_log(),
                    )
                continue
            content_type = (item.get("content_type") or "image/jpeg").strip() or "image/jpeg"
            url = upload_notice_image(
                raw,
                college_id=college_id,
                external_id=external_id,
                index=idx,
                content_type=content_type,
                filename_hint=name,
            )
            if url:
                resolved.append({"url": url, "name": name})
            continue

        url_str = (item.get("url") or item.get("src") or "").strip()
        if not url_str and data and isinstance(data, str):
            url_str = data.strip()
        if _is_valid_url_scheme(url_str):
            resolved.append({"url": url_str, "name": name})
    return resolved


def _external_id_from_url(url: str, ctx: CrawlLogContext | None = None) -> str:
    """URL에서 external_id 추출 (no가 없을 때 사용). path 또는 articleNo 등. 해시 fallback 시 path만 사용."""
    try:
        p = urlparse(url)
        q = parse_qs(p.query)
        for key in ("articleNo", "article_no", "no", "id", "idx"):
            if q.get(key):
                return str(q[key][0])
        segment = p.path.rstrip("/").split("/")[-1]
        if segment and segment.isalnum():
            return segment
        path_only = _url_path_only_for_hash(url)
        return hashlib.sha256(path_only.encode()).hexdigest().lower()[:32]
    except (ValueError, KeyError, AttributeError, IndexError) as e:
        logger.warning(
            "_external_id_from_url fallback to hash: url=%s error=%s",
            url[:200] if url else "",
            e,
            extra=ctx.extra_for_log() if ctx else {},
        )
        _capture_crawl_sentry_exception("crawl_payload:external_id_fallback", e, ctx=ctx)
        path_only = _url_path_only_for_hash(url)
        return hashlib.sha256(path_only.encode()).hexdigest().lower()[:32]


def _content_hash_from_title_and_html(
    title: str,
    content_html: str | None,
    body_text: str | None = None,
    *,
    attachments: list | None = None,
    images: list | None = None,
) -> str:
    """제목 + 본문 텍스트 + 첨부/이미지 시그니처로 sha256. 첨부·이미지 변경 시 갱신 감지."""
    if body_text is not None:
        text_for_hash = body_text
    else:
        text_for_hash = ""
        if content_html:
            soup = BeautifulSoup(content_html, "html.parser")
            text_for_hash = soup.get_text(separator="\n", strip=True)
    parts = [title or "", text_for_hash]
    if attachments:
        names = sorted(str(a.get("name", a) if isinstance(a, dict) else a) for a in attachments)
        parts.append("\n".join(names))
    if images:
        urls = sorted(str(img.get("url", img.get("src", ""))) for img in images if isinstance(img, dict))
        parts.append("\n".join(urls))
    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_published_at(date_str: str | None, ctx: CrawlLogContext | None = None) -> datetime | None:
    """YYYY.MM.DD 등 문자열을 timezone-aware datetime으로. 실패 시 None."""
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
            extra=ctx.extra_for_log() if ctx else {},
        )
        _capture_crawl_sentry_message(
            "crawl_payload:parse_published_at_no_match",
            "_parse_published_at no match (format change?)",
            level="warning",
            ctx=ctx,
        )
    except (ValueError, AttributeError, TypeError) as e:
        logger.warning(
            "_parse_published_at failed: date_str=%r error=%s",
            date_str[:100] if date_str else None,
            e,
            exc_info=True,
            extra=ctx.extra_for_log() if ctx else {},
        )
        _capture_crawl_sentry_exception("crawl_payload:parse_published_at_exception", e, ctx=ctx)
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
    post: LinkItem | dict[str, Any],
    detail_url: str,
    title: str,
    date_str: str | None,
    html_content: str | None,
    images: list | None,
    attachments: list | None,
    body_text_for_hash: str | None = None,
    external_id: str | None = None,
    ctx: CrawlLogContext | None = None,
) -> NoticeDraft | None:
    """
    한 건 공지 스크랩 결과 → upsert용 NoticeDraft. 스킵 시 None(로깅 후 반환).
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
    external_id_value = external_id or post.get("no") or _external_id_from_url(detail_url, ctx=ctx)
    att_dicts = _attachments_to_dicts(attachments or [])
    images_resolved = _resolve_notice_images(
        images or [],
        college_id=college_id,
        external_id=external_id_value,
        ctx=ctx,
    )
    images_filtered = _filter_valid_urls(images_resolved)
    att_dicts = [a for a in att_dicts if "url" not in a or _is_valid_url_scheme(a.get("url") or "")]
    content_hash = _content_hash_from_title_and_html(
        title,
        html_content,
        body_text_for_hash,
        attachments=attachments or [],
        images=images_resolved,
    )
    published_at = _parse_published_at(date_str, ctx=ctx)
    content_url = upload_notice_html(
        html_content,
        college_id=college_id,
        external_id=external_id_value,
        content_hash=content_hash,
    )
    if content_url is None or (isinstance(content_url, str) and not content_url.strip()):
        if ctx:
            logger.debug(
                "content_url empty (backfill candidate): college_id=%s external_id=%s url=%s",
                college_id,
                external_id_value,
                detail_url[:200] if detail_url else "",
                extra=ctx.extra_for_log(),
            )
    return NoticeDraft(
        college_id=college_id,
        external_id=external_id_value,
        title=title,
        url=detail_url or None,
        content_url=content_url or None,
        images=images_filtered,
        attachments=att_dicts,
        content_hash=content_hash,
        published_at=published_at,
    )
