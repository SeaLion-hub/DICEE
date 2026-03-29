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
CRAWL_RETRY_TOTAL = "crawl_retry_total"
CRAWL_DROP_TOTAL = "crawl_drop_total"
CRAWL_PARSE_THRESHOLD_TRIGGER_TOTAL = "crawl_parse_threshold_trigger_total"
CRAWL_DISPATCH_ENQUEUED_TOTAL = "crawl_dispatch_enqueued_total"
CRAWL_DISPATCH_BACKPRESSURE_TOTAL = "crawl_dispatch_backpressure_total"
CRAWL_DISPATCH_MEMORY_MB = "crawl_dispatch_memory_mb"
CRAWL_DISPATCH_NET_SENT_MB = "crawl_dispatch_net_sent_mb"
CRAWL_DISPATCH_NET_RECV_MB = "crawl_dispatch_net_recv_mb"
# 워커 크롤 1회 실행 동안 upsert 대기 chunk(list) 길이 피크. 라벨: college_code
CRAWL_PIPELINE_PEAK_PENDING_DRAFTS = "crawl_pipeline_peak_pending_drafts"

# POST /internal/trigger-crawl 오케스트레이션 (라벨: college_code)
INTERNAL_TRIGGER_CRAWL_ENQUEUED_TOTAL = "internal_trigger_crawl_enqueued_total"
INTERNAL_TRIGGER_CRAWL_SKIPPED_LOCK_TOTAL = "internal_trigger_crawl_skipped_lock_total"
INTERNAL_TRIGGER_CRAWL_ENQUEUE_FAILED_TOTAL = "internal_trigger_crawl_enqueue_failed_total"

# reason 라벨 값 (고정 enum, 카디널리티 제한)
RETRY_REASON_TIMEOUT = "timeout"
RETRY_REASON_429 = "429"
RETRY_REASON_5XX = "5xx"
RETRY_REASON_NETWORK = "network"
DROP_REASON_SKIPPABLE_HTTP = "skippable_http"
DROP_REASON_RETRYABLE_DONE = "retryable_done"
DROP_REASON_BODY_TOO_LARGE = "body_too_large"
DROP_REASON_DUPLICATE = "duplicate"
DROP_REASON_PRE_DEDUP = "pre_dedup"
DROP_REASON_PAYLOAD_BUILD_NONE = "payload_build_none"

INTERNAL_AUTH_FAILED_TOTAL = "internal_auth_failed_total"
INTERNAL_PREAUTH_RATE_LIMITED_TOTAL = "internal_preauth_rate_limited_total"
CLIENT_IP_RESOLUTION_TOTAL = "client_ip_resolution_total"
INVALID_XFF_TOTAL = "invalid_xff_total"
REFRESH_TOKEN_REUSE_ATTEMPT_TOTAL = "refresh_token_reuse_attempt_total"

# Read cache (soft TTL + mutex)
READ_CACHE_FRESH_HIT_TOTAL = "read_cache_fresh_hit_total"
READ_CACHE_STALE_HIT_TOTAL = "read_cache_stale_hit_total"
READ_CACHE_MISS_TOTAL = "read_cache_miss_total"
READ_CACHE_REFRESH_TOTAL = "read_cache_refresh_total"
READ_CACHE_WAIT_TOTAL = "read_cache_wait_total"

# API 골든 시그널 (라벨 허용 목록: endpoint_template, status_class, method 만 사용)
REQUEST_TOTAL = "request_total"
REQUEST_ERROR_TOTAL = "request_error_total"
REQUEST_DURATION_SECONDS = "request_duration_seconds"

# AI 추출 (라벨: status=ok|fallback|error,
# reason=validation_error|validation_retry_exhausted|provider_error|raw_substring_validation_failed)
AI_EXTRACTION_ATTEMPT_TOTAL = "ai_extraction_attempt_total"
AI_EXTRACTION_SUCCESS_TOTAL = "ai_extraction_success_total"
AI_EXTRACTION_FALLBACK_TOTAL = "ai_extraction_fallback_total"
AI_EXTRACTION_VALIDATION_ERROR_TOTAL = "ai_extraction_validation_error_total"
AI_EXTRACTION_PROVIDER_ERROR_TOTAL = "ai_extraction_provider_error_total"
AI_EXTRACTION_TOKENS_TOTAL = "ai_extraction_tokens_total"

# 크롤 완료 후 process_notice_ai_batch_task.delay() 브로커 적재 실패 (라벨: college_code)
AI_ENQUEUE_FAILED_TOTAL = "ai_enqueue_failed_total"
# AI 결과 DB 반영 완료(매칭·알림 파이프라인 훅). 라벨: college_code (= colleges.external_id)
NOTICE_AI_EXTRACTION_COMPLETED_TOTAL = "notice_ai_extraction_completed_total"

ALLOWED_REQUEST_LABELS = frozenset({"endpoint_template", "status_class", "method"})


def _labels_for_request_metrics(labels: dict[str, str]) -> dict[str, str]:
    """허용 목록 외 라벨 제거. 카디널리티 폭주 방지."""
    return {k: v for k, v in labels.items() if k in ALLOWED_REQUEST_LABELS}


def _make_key(name: str, labels: dict[str, str] | None) -> str:
    """Prometheus 스타일의 복합 키 생성: name{k="v",...}"""
    if not labels:
        return name
    label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{label_str}}}"


def increment(name: str, value: int = 1, labels: dict[str, str] | None = None) -> None:
    if name in (REQUEST_TOTAL, REQUEST_ERROR_TOTAL) and labels:
        labels = _labels_for_request_metrics(labels)
    key = _make_key(name, labels)
    with _lock:
        _counters[key] = _counters.get(key, 0) + value


def set_gauge(name: str, value: float, labels: dict[str, str] | None = None) -> None:
    if name == REQUEST_DURATION_SECONDS and labels:
        labels = _labels_for_request_metrics(labels)
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
