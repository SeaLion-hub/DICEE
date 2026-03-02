"""
?щ·??怨듯넻 HTTP ?섑띁. OOM 諛⑹?: Content-Length fail-fast + 臾댁“嫄?stream chunking.
?낆쓽???쒕쾭媛 Content-Length瑜??띿뿬???꾩쟻 諛붿씠??罹≪쑝濡?諛⑹뼱.
?숆린(?뚯빱?? fetch_html, 鍮꾨룞湲??뱀슜) fetch_html_async.
?곸꽭 ?섏씠吏 read-through 罹먯떆: fetch_html_detail_cached (紐⑸줉? 誘몄틦??.
"""

import hashlib
import logging
from typing import Any

import httpx
import requests

from app.core.config import settings
from app.core.redis import get_shared_sync_redis_client
from app.services.crawl.downloader_middleware import (
    DownloadRequest,
    DownloadResponse,
    get_default_async_downloader_manager,
    get_default_sync_downloader_manager,
)

logger = logging.getLogger(__name__)

# 湲곕낯 理쒕? HTML 諛붿씠??(crawl_service.MAX_HTML_BYTES? ?숈씪 媛??좎?)
DEFAULT_MAX_HTML_BYTES = 10 * 1024 * 1024
DEFAULT_TIMEOUT = 10
CHUNK_SIZE = 64 * 1024


class HtmlTooLargeError(Exception):
    """?묐떟 蹂몃Ц??max_bytes瑜?珥덇낵??(OOM 諛⑹?)."""

    pass


def fetch_html(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_HTML_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, Any] | None = None,
    encoding: str = "utf-8",
    request_meta: dict[str, Any] | None = None,
) -> str:
    """
    URL?먯꽌 HTML 臾몄옄?댁쓣 ?덉쟾?섍쾶 媛?몄샂.
    - Content-Length媛 ?덉쑝硫?max_bytes 珥덇낵 ??蹂몃Ц ?쎄린 ?꾩뿉 HtmlTooLargeError.
    - ?ㅼ젣 ?쎄린??臾댁“嫄?stream + iter_content; ?꾩쟻??max_bytes 珥덇낵 ??利됱떆 close ??HtmlTooLargeError.
    - encoding: ?붿퐫?⑹뿉 ?ъ슜 (湲곕낯 utf-8, cp949 ??.
    """
    manager = get_default_sync_downloader_manager()
    request = DownloadRequest(
        url=url,
        timeout=timeout,
        headers=headers,
        meta=dict(request_meta or {}),
    )

    response = manager.fetch(
        request,
        lambda req: _fetch_html_stream_sync(req, max_bytes=max_bytes, encoding=encoding),
    )
    return response.body


def _fetch_html_stream_sync(
    request: DownloadRequest,
    *,
    max_bytes: int,
    encoding: str,
) -> DownloadResponse:
    """Single HTTP fetch with stream-size guard. Retry/rate-limit are handled by middleware."""
    resp = requests.get(request.url, headers=request.headers, timeout=request.timeout, stream=True)
    try:
        resp.raise_for_status()
    except Exception:
        resp.close()
        raise

    # Fail-fast: Content-Length媛 ?덇퀬 珥덇낵?섎㈃ 蹂몃Ц ?쎌? ?딆쓬
    cl = resp.headers.get("Content-Length")
    if cl:
        try:
            if int(cl) > max_bytes:
                resp.close()
                raise HtmlTooLargeError(f"Content-Length {cl} > max_bytes {max_bytes}; url={request.url[:200]}")
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
                        f"Accumulated {accumulated} > max_bytes {max_bytes}; url={request.url[:200]}"
                    )
                chunks.append(chunk)
    finally:
        resp.close()
    return DownloadResponse(
        url=request.url,
        body=b"".join(chunks).decode(encoding, errors="replace"),
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )


def _detail_cache_key(url: str, encoding: str) -> str:
    """罹먯떆 ?? prefix + hash(url|encoding). URL 湲몄씠 ?쒗븳 ?뚰뵾."""
    raw = f"{url}|{encoding}"
    h = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    prefix = getattr(settings, "crawl_detail_cache_key_prefix", "dicee:crawl:detail:")
    return f"{prefix.rstrip(':')}:{h}"


def fetch_html_detail_cached(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_HTML_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, Any] | None = None,
    encoding: str = "utf-8",
    request_meta: dict[str, Any] | None = None,
) -> str:
    """
    ?곸꽭 ?섏씠吏??read-through 罹먯떆. hit ??利됱떆 諛섑솚, miss ??fetch ??setex.
    Redis ?μ븷/誘몄꽕????fail-open(fetch_html ?몄텧). 紐⑸줉 ?섏씠吏?먮뒗 ?ъ슜?섏? 留?寃?
    """
    enabled = getattr(settings, "crawl_detail_cache_enabled", False)
    client = get_shared_sync_redis_client()
    if not enabled or client is None:
        return fetch_html(
            url,
            max_bytes=max_bytes,
            timeout=timeout,
            headers=headers,
            encoding=encoding,
            request_meta=request_meta,
        )
    key = _detail_cache_key(url, encoding)
    ttl = getattr(settings, "crawl_detail_cache_ttl_seconds", 300)
    try:
        cached = client.get(key)
        if cached is not None:
            return str(cached)
    except Exception as e:
        logger.debug("crawl detail cache get failed: key=%s error=%s", key[:80], e)
        return fetch_html(
            url,
            max_bytes=max_bytes,
            timeout=timeout,
            headers=headers,
            encoding=encoding,
            request_meta=request_meta,
        )
    html = fetch_html(
        url,
        max_bytes=max_bytes,
        timeout=timeout,
        headers=headers,
        encoding=encoding,
        request_meta=request_meta,
    )
    try:
        client.setex(key, ttl, html)
    except Exception as e:
        logger.debug("crawl detail cache set failed: key=%s error=%s", key[:80], e)
    return html


async def fetch_html_async(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_HTML_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, Any] | None = None,
    encoding: str = "utf-8",
    request_meta: dict[str, Any] | None = None,
) -> str:
    """
    鍮꾨룞湲? URL?먯꽌 HTML 臾몄옄?댁쓣 ?덉쟾?섍쾶 媛?몄샂 (stream + 泥?겕).
    OOM 諛⑹?: Content-Length 珥덇낵 ??蹂몃Ц ?쎌? ?딆쓬; ?꾩쟻 珥덇낵 ??HtmlTooLargeError.
    max_bytes 珥덇낵 ??利됱떆 HtmlTooLargeError 諛쒖깮쨌?ㅽ듃由?醫낅즺(?먮윭 硫붿떆吏??url ?쇰? ?ы븿).
    encoding: ?붿퐫?⑹뿉 ?ъ슜 (湲곕낯 utf-8, cp949 ??.
    """
    manager = get_default_async_downloader_manager()
    request = DownloadRequest(
        url=url,
        timeout=timeout,
        headers=headers,
        meta=dict(request_meta or {}),
    )
    response = await manager.fetch(
        request,
        lambda req: _fetch_html_stream_async(client, req, max_bytes=max_bytes, encoding=encoding),
    )
    return response.body


async def _fetch_html_stream_async(
    client: httpx.AsyncClient,
    request: DownloadRequest,
    *,
    max_bytes: int,
    encoding: str,
) -> DownloadResponse:
    """Single async HTTP fetch with stream-size guard. Retry/rate-limit are handled by middleware."""
    async with client.stream("GET", request.url, headers=request.headers, timeout=request.timeout) as response:
        response.raise_for_status()
        cl = response.headers.get("Content-Length")
        if cl:
            try:
                if int(cl) > max_bytes:
                    raise HtmlTooLargeError(f"Content-Length {cl} > max_bytes {max_bytes}; url={request.url[:200]}")
            except ValueError:
                pass
        accumulated = 0
        chunks: list[bytes] = []
        async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
            if chunk:
                accumulated += len(chunk)
                if accumulated > max_bytes:
                    raise HtmlTooLargeError(
                        f"Accumulated {accumulated} > max_bytes {max_bytes}; url={request.url[:200]}"
                    )
                chunks.append(chunk)
    return DownloadResponse(
        url=request.url,
        body=b"".join(chunks).decode(encoding, errors="replace"),
        status_code=response.status_code,
        headers=dict(response.headers),
    )

