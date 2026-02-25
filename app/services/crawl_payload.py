"""
크롤 파싱·페이로드 빌드. 순수 함수 및 스크랩 결과 → Notice upsert용 payload 변환.
HTTP/DB 미의존. crawl_service 오케스트레이터에서 import해 사용.
"""

import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.core.storage import upload_notice_html

logger = logging.getLogger(__name__)

MAX_HTML_BYTES = 5 * 1024 * 1024  # 본문 HTML 최대 바이트. 초과 시 해당 공지 스킵(OOM 방지).


def _url_path_only_for_hash(url: str) -> str:
    """해시 fallback용: 쿼리 제거, path만 사용."""
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
        except (OSError, Exception) as sentry_err:
            logger.warning("Sentry capture_exception failed: %s", sentry_err)
        path_only = _url_path_only_for_hash(url)
        return hashlib.sha256(path_only.encode()).hexdigest()[:32]


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
        names = sorted(
            str(a.get("name", a) if isinstance(a, dict) else a) for a in attachments
        )
        parts.append("\n".join(names))
    if images:
        urls = sorted(
            str(img.get("url", img.get("src", "")))
            for img in images
            if isinstance(img, dict)
        )
        parts.append("\n".join(urls))
    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_published_at(date_str: str | None) -> datetime | None:
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
        )
        try:
            import sentry_sdk
            sentry_sdk.capture_message(
                f"_parse_published_at no match (format change?): date_str={date_str[:100]!r}",
                level="warning",
            )
        except (OSError, Exception) as sentry_err:
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
        except (OSError, Exception) as sentry_err:
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
    att_dicts = _attachments_to_dicts(attachments or [])
    content_hash = _content_hash_from_title_and_html(
        title,
        html_content,
        body_text_for_hash,
        attachments=attachments or [],
        images=images or [],
    )
    published_at = _parse_published_at(date_str)
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
