"""인메모리 메트릭(KPI). lock·crawl·upload 등. 레이블 지원·Prometheus 포맷 노출."""

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

# 신규 KPI (Prometheus·대시보드용)
CRAWL_SUCCESS_TOTAL = "crawl_success_total"
CRAWL_FAILURE_TOTAL = "crawl_failure_total"
CRAWL_ATTEMPT_TOTAL = "crawl_attempt_total"
CRAWL_PARSER_FAILURE_TOTAL = "crawl_parser_failure_total"


def _make_key(name: str, labels: dict[str, str] | None) -> str:
    """Prometheus 스타일의 복합 키 생성: name{k="v",...}"""
    if not labels:
        return name
    label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{label_str}}}"


def increment(name: str, value: int = 1, labels: dict[str, str] | None = None) -> None:
    key = _make_key(name, labels)
    with _lock:
        _counters[key] = _counters.get(key, 0) + value


def set_gauge(name: str, value: float, labels: dict[str, str] | None = None) -> None:
    key = _make_key(name, labels)
    with _lock:
        _gauges[key] = value


def get_counter(name: str, labels: dict[str, str] | None = None) -> int:
    key = _make_key(name, labels)
    with _lock:
        return _counters.get(key, 0)


def get_gauge(name: str, labels: dict[str, str] | None = None) -> float | None:
    key = _make_key(name, labels)
    with _lock:
        return _gauges.get(key)


def get_all() -> dict[str, Any]:
    """현재 메트릭 스냅샷. /metrics 또는 로깅용."""
    with _lock:
        return {"counters": dict(_counters), "gauges": dict(_gauges)}
