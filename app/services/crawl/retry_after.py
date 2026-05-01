"""Retry-After parsing shared by crawl retry policies."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

CRAWL_RETRY_BASE_SEC = 1.0
CRAWL_RETRY_MAX_SEC = 60.0


def parse_retry_after_seconds(response: Any) -> float | None:
    """
    RFC 7231 Retry-After: delta-seconds (integer) or HTTP-date.
    wait_seconds = retry_after_datetime - now for HTTP-date (positive if server time in future).
    Returns None if header absent, invalid, negative, or oversized (then use fallback).
    """
    if response is None or not hasattr(response, "headers"):
        return None
    raw = response.headers.get("Retry-After")
    if not raw or not str(raw).strip():
        return None
    raw = str(raw).strip()
    try:
        secs: float
        if raw.isdigit():
            secs = float(int(raw))
        else:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            secs = (dt - now).total_seconds()
        if secs < 0:
            return None
        if secs < CRAWL_RETRY_BASE_SEC:
            secs = CRAWL_RETRY_BASE_SEC
        if secs > CRAWL_RETRY_MAX_SEC:
            secs = CRAWL_RETRY_MAX_SEC
        return secs
    except (ValueError, TypeError, OSError):
        return None
