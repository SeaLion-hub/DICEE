"""
크롤러 공통 HTTP 래퍼. OOM 방지: Content-Length fail-fast + 무조건 stream chunking.
악의적 서버가 Content-Length를 속여도 누적 바이트 캡으로 방어.
동기(워커용) fetch_html, 비동기(웹용) fetch_html_async.
"""

import logging
from typing import Any

import httpx
import requests

from app.core.crawler_config import CRAWLER_HEADERS

logger = logging.getLogger(__name__)

# 기본 최대 HTML 바이트 (crawl_service.MAX_HTML_BYTES와 동일 값 유지)
DEFAULT_MAX_HTML_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 10
CHUNK_SIZE = 64 * 1024


class HtmlTooLargeError(Exception):
    """응답 본문이 max_bytes를 초과함 (OOM 방지)."""
    pass


def fetch_html(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_HTML_BYTES,
    timeout: int = DEFAULT_TIMEOUT,
    headers: dict[str, Any] | None = None,
    encoding: str = "utf-8",
) -> str:
    """
    URL에서 HTML 문자열을 안전하게 가져옴.
    - Content-Length가 있으면 max_bytes 초과 시 본문 읽기 전에 HtmlTooLargeError.
    - 실제 읽기는 무조건 stream + iter_content; 누적이 max_bytes 초과 시 즉시 close 후 HtmlTooLargeError.
    - encoding: 디코딩에 사용 (기본 utf-8, cp949 등).
    """
    h = headers or CRAWLER_HEADERS
    resp = requests.get(url, headers=h, timeout=timeout, stream=True)
    try:
        resp.raise_for_status()
    except Exception:
        resp.close()
        raise

    # Fail-fast: Content-Length가 있고 초과하면 본문 읽지 않음
    cl = resp.headers.get("Content-Length")
    if cl:
        try:
            if int(cl) > max_bytes:
                resp.close()
                raise HtmlTooLargeError(
                    f"Content-Length {cl} > max_bytes {max_bytes}; url={url[:200]}"
                )
        except ValueError:
            pass

    accumulated = 0
    chunks: list[bytes] = []
    try:
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
            if chunk:
                accumulated += len(chunk)
                if accumulated > max_bytes:
                    resp.close()
                    raise HtmlTooLargeError(
                        f"Accumulated {accumulated} > max_bytes {max_bytes}; url={url[:200]}"
                    )
                chunks.append(chunk)
    finally:
        resp.close()

    return b"".join(chunks).decode(encoding, errors="replace")


async def fetch_html_async(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_HTML_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, Any] | None = None,
    encoding: str = "utf-8",
) -> str:
    """
    비동기: URL에서 HTML 문자열을 안전하게 가져옴 (stream + 청크).
    OOM 방지: Content-Length 초과 시 본문 읽지 않음; 누적 초과 시 HtmlTooLargeError.
    max_bytes 초과 시 즉시 HtmlTooLargeError 발생·스트림 종료(에러 메시지에 url 일부 포함).
    encoding: 디코딩에 사용 (기본 utf-8, cp949 등).
    """
    h = headers or CRAWLER_HEADERS
    async with client.stream("GET", url, headers=h, timeout=timeout) as response:
        response.raise_for_status()
        cl = response.headers.get("Content-Length")
        if cl:
            try:
                if int(cl) > max_bytes:
                    raise HtmlTooLargeError(
                        f"Content-Length {cl} > max_bytes {max_bytes}; url={url[:200]}"
                    )
            except ValueError:
                pass
        accumulated = 0
        chunks: list[bytes] = []
        async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
            if chunk:
                accumulated += len(chunk)
                if accumulated > max_bytes:
                    raise HtmlTooLargeError(
                        f"Accumulated {accumulated} > max_bytes {max_bytes}; url={url[:200]}"
                    )
                chunks.append(chunk)
    return b"".join(chunks).decode(encoding, errors="replace")
