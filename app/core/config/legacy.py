import os
import threading

_legacy_guard_allow = threading.local()

_LEGACY_CONFIG_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "database_url",
        "db_connect_retries",
        "db_connect_retry_interval_sec",
        "strict_startup_db_check",
        "db_pool_size_async",
        "db_pool_max_overflow_async",
        "db_pool_timeout_async",
        "db_pool_recycle_async",
        "db_statement_timeout_ms",
        "db_pool_size_sync",
        "db_pool_max_overflow_sync",
        "db_pool_timeout_sync",
        "db_pool_recycle_sync",
        "db_max_connections",
        "db_reserved",
        "db_pool_strict_budget",
        "deploy_surge_factor",
        "db_api_instances",
        "db_uvicorn_workers",
        "db_worker_instances",
        "db_celery_concurrency",
        "redis_url",
        "redis_ca_certs",
        "redis_socket_timeout",
        "redis_socket_connect_timeout",
        "redis_blocklist_fail_closed",
        "redis_blocklist_circuit_failure_threshold",
        "redis_blocklist_circuit_open_seconds",
        "redis_blocklist_circuit_half_open_interval_seconds",
        "redis_blocklist_max_connections",
        "redis_trigger_lock_max_connections",
        "redis_trigger_lock_ttl_seconds",
        "redis_trigger_lock_required",
        "redis_trigger_idempotency_required",
    }
)


def is_legacy_config_forbidden() -> bool:
    return os.environ.get("LEGACY_CONFIG_FORBIDDEN", "").strip().lower() in ("true", "1")
