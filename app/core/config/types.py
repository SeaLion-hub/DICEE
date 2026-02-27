from typing import NamedTuple


class _DatabaseConfig(NamedTuple):
    database_url: str | None
    db_connect_retries: int
    db_connect_retry_interval_sec: float
    strict_startup_db_check: bool
    db_pool_size_async: int
    db_pool_max_overflow_async: int
    db_pool_timeout_async: float
    db_statement_timeout_ms: int
    db_pool_size_sync: int
    db_pool_max_overflow_sync: int
    db_pool_timeout_sync: float
    db_pool_recycle_sync: int
    db_max_connections: int | None
    db_reserved: int
    db_pool_strict_budget: bool
    deploy_surge_factor: float
    db_api_instances: int
    db_uvicorn_workers: int
    db_worker_instances: int
    db_celery_concurrency: int


class _RedisConfig(NamedTuple):
    redis_url: str | None
    redis_ca_certs: str | None
    redis_socket_timeout: float
    redis_socket_connect_timeout: float
    redis_blocklist_fail_closed: bool
    redis_blocklist_circuit_failure_threshold: int
    redis_blocklist_circuit_open_seconds: float
    redis_blocklist_circuit_half_open_interval_seconds: float
    redis_blocklist_max_connections: int
    redis_trigger_lock_max_connections: int
    redis_trigger_lock_ttl_seconds: int
    redis_trigger_lock_required: bool
    redis_trigger_idempotency_required: bool
    redis_crawl_seen_required: bool
