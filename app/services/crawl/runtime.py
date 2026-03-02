"""Crawl runtime config, seen sets, and resolve/cap helpers."""

import logging
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Any

from tenacity import RetryCallState, wait_exponential_jitter

from app.core.config import settings
from app.core.crawler_config import COLLEGE_CODE_TO_MODULE, CRAWLER_CONFIG
from app.core.redis import get_shared_sync_redis_client
from app.domain.contracts.crawl_contracts import LinkItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CrawlRuntimeConfig:
    polite_delay_seconds: float
    page_timeout_seconds: float
    upsert_chunk_size: int
    collect_sync_max_workers: int
    collect_in_flight_limit: int
    max_links_per_run: int
    collect_async_concurrency: int
    crawl_seen_max_size: int


@lru_cache(maxsize=1)
def _load_crawl_runtime_config() -> CrawlRuntimeConfig:
    """Load crawl runtime config once per process and reuse via cache."""
    return CrawlRuntimeConfig(
        polite_delay_seconds=settings.polite_delay_seconds,
        page_timeout_seconds=settings.crawl_page_timeout_seconds,
        upsert_chunk_size=settings.crawl_upsert_chunk_size,
        collect_sync_max_workers=settings.crawl_collect_sync_max_workers,
        collect_in_flight_limit=settings.crawl_collect_in_flight_limit,
        max_links_per_run=settings.crawl_max_links_per_run,
        collect_async_concurrency=settings.crawl_collect_async_concurrency,
        crawl_seen_max_size=settings.crawl_seen_max_size,
    )


CRAWL_RETRY_BASE_SEC = 1.0
CRAWL_RETRY_MAX_SEC = 60.0
CRAWL_RETRY_MAX_ATTEMPTS = 5
_crawl_retry_wait = wait_exponential_jitter(
    initial=CRAWL_RETRY_BASE_SEC,
    max=CRAWL_RETRY_MAX_SEC,
    jitter=1.0,
)


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


def get_crawl_retry_wait(retry_state: RetryCallState) -> float:
    """
    Tenacity wait: 429 and Retry-After present → use parsed seconds (capped);
    otherwise exponential+jitter fallback.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc is not None and hasattr(exc, "response") and exc.response is not None:
        code = getattr(exc.response, "status_code", None)
        if code == 429:
            secs = parse_retry_after_seconds(exc.response)
            if secs is not None:
                return secs
    return _crawl_retry_wait(retry_state)


class _BoundedSeenSet:
    """최대 max_size개 external_id만 유지. 초과 시 가장 오래된 항목 evict. O(1) add/contains."""

    __slots__ = ("_deque", "_set", "_max_size")

    def __init__(self, max_size: int | None = None) -> None:
        self._deque: deque[str] = deque()
        self._set: set[str] = set()
        self._max_size = max_size or settings.crawl_seen_max_size

    def add(self, x: str) -> None:
        if x in self._set:
            return
        while len(self._set) >= self._max_size and self._deque:
            oldest = self._deque.popleft()
            self._set.discard(oldest)
        self._deque.append(x)
        self._set.add(x)

    def __contains__(self, x: str) -> bool:
        return x in self._set


CRAWL_SEEN_REDIS_KEY_PREFIX = "dicee:crawl_seen:"
CRAWL_SEEN_REDIS_TTL_SECONDS = 3600


class _RedisSeenSet:
    """
    Redis SET 기반 분산 Seen Set. run_id 단위로 워커 간 이미 본 URL 공유.
    멀티 워커 환경에서 동일 URL 중복 크롤 방지(필수). add/__contains__ 인터페이스.
    """

    __slots__ = ("_key", "_client", "_ttl", "_closed", "_required", "_run_id")

    def __init__(
        self,
        run_id: uuid.UUID,
        _redis_url: str,
        ttl_seconds: int = CRAWL_SEEN_REDIS_TTL_SECONDS,
        *,
        required: bool = False,
    ) -> None:
        self._key = f"{CRAWL_SEEN_REDIS_KEY_PREFIX}{run_id}"
        self._run_id = run_id
        self._ttl = ttl_seconds
        self._closed = False
        self._required = required
        self._client: Any | None = None

    def _ensure_client(self) -> None:
        if self._client is not None or self._closed:
            return
        try:
            self._client = get_shared_sync_redis_client()
        except Exception as e:
            if self._required:
                raise RuntimeError(f"Redis Seen Set required but connection failed (run_id={self._run_id}): {e}") from e
            logger.warning("RedisSeenSet connect failed: %s; falling back to in-memory", e)
        if self._client is None and self._required:
            raise RuntimeError(
                f"Redis Seen Set required but connection failed (run_id={self._run_id}): redis client unavailable"
            )

    def add(self, x: str) -> None:
        self._ensure_client()
        if self._client is None:
            if self._required:
                raise RuntimeError("Redis Seen Set required but client is unavailable (init failed).")
            return
        try:
            pipe = self._client.pipeline()
            pipe.sadd(self._key, x)
            pipe.expire(self._key, self._ttl)
            pipe.execute()
        except Exception as e:
            if self._required:
                raise RuntimeError(f"Redis Seen Set add failed (required): {e}") from e
            logger.warning("RedisSeenSet add failed: %s", e)

    def __contains__(self, x: str) -> bool:
        self._ensure_client()
        if self._client is None:
            if self._required:
                raise RuntimeError("Redis Seen Set required but client is unavailable (init failed).")
            return False
        try:
            return bool(self._client.sismember(self._key, x))
        except Exception as e:
            if self._required:
                raise RuntimeError(f"Redis Seen Set __contains__ failed (required): {e}") from e
            logger.warning("RedisSeenSet __contains__ failed: %s", e)
            return False

    def close(self) -> None:
        if getattr(self, "_closed", True) or self._client is None:
            return
        self._closed = True


_SeenSet = set[str] | _BoundedSeenSet | _RedisSeenSet


def _resolve_module_and_list_url(college_code: str) -> tuple[str, str]:
    module_name = COLLEGE_CODE_TO_MODULE.get(college_code)
    if not module_name:
        raise ValueError(f"No crawler module for college: {college_code}")
    config = CRAWLER_CONFIG.get(module_name)
    if not config or not config.get("url"):
        raise ValueError(f"No crawler config or url for: {module_name}")
    return module_name, config["url"]


def _cap_links_for_run(links_raw: list[LinkItem], college_code: str, max_links: int) -> list[LinkItem]:
    if len(links_raw) > max_links:
        logger.warning(
            "Links capped for OOM prevention: college_code=%s total=%d cap=%d",
            college_code,
            len(links_raw),
            max_links,
        )
    return links_raw[:max_links]


def _init_seen_set_async(seen_max_size: int) -> _BoundedSeenSet:
    """비동기 파이프라인 전용. in-memory만 사용."""
    return _BoundedSeenSet(seen_max_size)


def _init_seen_set_sync(
    *,
    run_id: uuid.UUID | None,
    redis_url: str,
    redis_required: bool,
    seen_max_size: int,
) -> _BoundedSeenSet | _RedisSeenSet:
    """동기 파이프라인 전용. run_id+redis_url 있으면 Redis, 아니면 in-memory."""
    if run_id and redis_url:
        return _RedisSeenSet(
            run_id,
            redis_url,
            CRAWL_SEEN_REDIS_TTL_SECONDS,
            required=redis_required,
        )
    return _BoundedSeenSet(seen_max_size)
