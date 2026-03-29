"""Worker outbound crawl proxy URL. Settings first, then CRAWLER_HTTP_PROXY env."""

from __future__ import annotations

import os
from typing import Any

from pydantic import SecretStr


def _secret_or_none(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    raw = value.get_secret_value().strip()
    return raw or None


def get_crawler_http_proxy_url(*, settings: Any | None = None) -> str | None:
    """
    Return HTTP(S) proxy URL for crawl workers, or None.

    Order: ``settings.crawler_http_proxy_url`` (if settings provided), else
    ``CRAWLER_HTTP_PROXY`` environment variable.
    """
    if settings is not None:
        url = _secret_or_none(getattr(settings, "crawler_http_proxy_url", None))
        if url:
            return url
    env_url = (os.environ.get("CRAWLER_HTTP_PROXY") or "").strip()
    return env_url or None


def crawler_requests_proxies(*, settings: Any | None = None) -> dict[str, str] | None:
    """``requests``/``httpx``-compatible proxies dict, or None when no proxy configured."""
    url = get_crawler_http_proxy_url(settings=settings)
    if not url:
        return None
    return {"http": url, "https": url}
