"""인메모리 메트릭(KPI). lock·crawl·upload 등. 추후 Prometheus/Sentry 연동 시 노출."""

from collections.abc import MutableMapping
from threading import Lock
from typing import Any

_lock = Lock()
_counters: MutableMapping[str, int] = {}
_gauges: MutableMapping[str, float] = {}

# KPI 이름 (계획서 기준)
LOCK_ACQUIRE_TOTAL = "lock_acquire_total"
LOCK_CONFLICT_TOTAL = "lock_conflict_total"
LOCK_EXPIRED_BEFORE_START_TOTAL = "lock_expired_before_start_total"
CRAWL_DURATION_SECONDS = "crawl_duration_seconds"
ENQUEUE_TO_START_LAG_SECONDS = "enqueue_to_start_lag_seconds"
CONTENT_UPLOAD_FAILURE_TOTAL = "content_upload_failure_total"
CRAWL_PARSER_FAILURE_RATIO = "crawl_parser_failure_ratio"


def increment(name: str, value: int = 1) -> None:
    with _lock:
        _counters[name] = _counters.get(name, 0) + value


def set_gauge(name: str, value: float) -> None:
    with _lock:
        _gauges[name] = value


def get_counter(name: str) -> int:
    with _lock:
        return _counters.get(name, 0)


def get_gauge(name: str) -> float | None:
    with _lock:
        return _gauges.get(name)


def get_all() -> dict[str, Any]:
    """현재 메트릭 스냅샷. /metrics 또는 로깅용."""
    with _lock:
        return {"counters": dict(_counters), "gauges": dict(_gauges)}
