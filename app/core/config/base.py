"""Settings model and validators."""

import logging
from typing import Literal
from urllib.parse import urlparse

from pydantic import (
    AliasChoices,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from .jwt import normalize_jwt_signing_mode, resolve_jwt_signing_algorithm
from .legacy import (
    _LEGACY_CONFIG_FIELD_NAMES,
    _legacy_guard_allow,
    is_legacy_config_forbidden,
)
from .parsing import _parse_allowed_origins
from .types import _DatabaseConfig, _RedisConfig

logger = logging.getLogger(__name__)
_POSTGRES_DSN_ADAPTER = TypeAdapter(PostgresDsn)
_REDIS_DSN_ADAPTER = TypeAdapter(RedisDsn)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Phase 1
    sentry_dsn: SecretStr | None = None
    sentry_release: str | None = Field(
        None,
        description="Sentry release identifier (e.g. version, git SHA). Unset = Sentry uses default.",
    )
    environment: Literal["development", "staging", "production", "test", "local"] = "development"

    # Entry point (required: no default — fail-fast when APP_ENTRY/ROLE missing)
    app_entry: Literal["api", "celery", "migrate"] = Field(
        ...,
        description="Entry point: api | celery | migrate. Set APP_ENTRY or ROLE.",
        validation_alias=AliasChoices("APP_ENTRY", "ROLE"),
    )

    # Phase 2+
    database_url: str | None = None
    db_connect_retries: int = Field(5, ge=1, le=20)
    db_connect_retry_interval_sec: float = Field(2.0, ge=0.5, le=60.0)
    strict_startup_db_check: bool = True

    db_pool_size_async: int = Field(4, ge=1, le=20)
    db_pool_max_overflow_async: int = Field(6, ge=0, le=20)
    db_pool_timeout_async: float = Field(5.0, ge=1.0, le=120.0)
    db_pool_recycle_async: int = Field(300, ge=-1, le=86400)
    db_statement_timeout_ms: int = Field(30000, ge=1000, le=300000)
    db_pool_size_sync: int = Field(2, ge=1, le=10)
    db_pool_max_overflow_sync: int = Field(0, ge=0, le=5)
    db_pool_timeout_sync: float = Field(30.0, ge=5.0, le=120.0)
    db_pool_recycle_sync: int = Field(300, ge=-1, le=86400)

    db_max_connections: int | None = Field(None, ge=1, le=1000)
    db_reserved: int = Field(3, ge=0, le=20)
    db_pool_strict_budget: bool = Field(False)
    deploy_surge_factor: float = Field(2.0, ge=1.0, le=4.0)
    db_api_instances: int = Field(1, ge=1, le=100)
    db_uvicorn_workers: int = Field(1, ge=1, le=32)
    db_worker_instances: int = Field(1, ge=1, le=100)
    db_celery_concurrency: int = Field(1, ge=1, le=32)

    trusted_proxy_ips: str = ""
    trusted_proxy_skip_fast: bool = Field(
        False,
        description=(
            "If True, skip production fail-fast for empty TRUSTED_PROXY_IPS. "
            "Set only when not behind a reverse proxy."
        ),
    )

    # Auth
    jwt_secret: SecretStr = SecretStr("")
    jwt_private_key_pem: SecretStr | None = None
    jwt_public_key_pem: SecretStr | None = None
    jwt_signing_mode: Literal["auto", "hs256", "rs256"] = Field(
        "auto",
        description=(
            "JWT signing mode. auto=prefer RS256 when complete key pair exists, "
            "fallback to HS256 when JWT_SECRET exists."
        ),
    )
    jwt_issuer: str = "dicee"
    jwt_audience: str = "dicee-api"
    jwt_access_expire_seconds: int = Field(600, ge=60, le=86400)
    jwt_refresh_expire_days: int = Field(7, ge=1, le=90)

    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uris: str = ""

    auth_google_rate_limit_per_minute: int = Field(28, ge=1, le=1000)
    auth_google_state_rate_limit_per_minute: int = Field(30, ge=1, le=500)
    auth_refresh_rate_limit_per_minute: int = Field(60, ge=1, le=5000)
    auth_refresh_token_fingerprint_rate_limit_per_minute: int = Field(15, ge=1, le=5000)

    # Crawler & Worker
    redis_url: str | None = None
    redis_celery_url: str | None = None
    redis_ca_certs: str | None = None
    redis_socket_timeout: float = Field(5.0, ge=1.0, le=60.0)
    redis_socket_connect_timeout: float = Field(2.0, ge=0.5, le=30.0)
    api_rate_limit_require_redis: bool = Field(False)

    redis_blocklist_fail_closed: bool = False
    redis_blocklist_circuit_failure_threshold: int = Field(3, ge=1, le=50)
    redis_blocklist_circuit_open_seconds: float = Field(60.0, ge=5.0, le=300.0)
    redis_blocklist_circuit_half_open_interval_seconds: float = Field(15.0, ge=2.0, le=60.0)
    redis_blocklist_max_connections: int = Field(20, ge=1, le=100)
    redis_trigger_lock_max_connections: int = Field(5, ge=1, le=50)
    redis_trigger_lock_ttl_seconds: int = Field(2400, ge=60, le=86400)
    redis_trigger_lock_required: bool = True
    redis_trigger_idempotency_required: bool = False
    redis_crawl_seen_required: bool = Field(False)

    crawl_trigger_secret: SecretStr | None = None
    internal_preauth_rate_limit_per_minute: int = Field(30, ge=1, le=10000)
    internal_auth_fail_rate_limit_per_minute: int = Field(10, ge=1, le=10000)
    internal_trigger_crawl_rate_limit_per_minute: int = Field(10, ge=1, le=1000)
    internal_crawl_stats_rate_limit_per_minute: int = Field(30, ge=1, le=1000)
    crawl_trigger_stagger_seconds: int = Field(
        300,
        ge=0,
        le=3600,
        description="단과대별 크롤 시작 시간 분산(초). Thundering Herd 방지. 0이면 동시 시작.",
    )
    client_ip_resolution_log_sample_rate: float = Field(0.0, ge=0.0, le=1.0)

    metrics_allowed_ips: str = Field(
        "",
        description="Comma-separated IPs allowed to scrape /internal/metrics. Empty = deny all.",
    )
    ai_pipeline_enabled: bool = False
    ai_batch_gemini_spacing_seconds: float = Field(
        6.0,
        ge=0.0,
        le=300.0,
        description=(
            "Sleep after each Gemini-backed extraction in process_notice_ai_batch_task. "
            "0 disables. Default ~6s approximates 10 external calls/min per worker."
        ),
    )
    gemini_api_key: SecretStr | None = Field(
        None,
        description="Gemini API key. When unset, google-generativeai uses GOOGLE_API_KEY from env.",
    )
    gemini_model: str = Field(
        "gemini-1.5-flash-latest",
        description="Gemini model id for AI extraction (tool-calling supported).",
    )
    ai_extraction_enforce_raw_substrings: bool = Field(
        False,
        description=(
            "When True (and no images), raw_eligibility_text and schedule date_raw "
            "must be substrings of prompt text. Skipped when image_urls are used (multimodal)."
        ),
    )
    celery_worker_prefetch_multiplier: int = Field(1, ge=1, le=16)
    celery_broker_connection_max_retries: int = Field(100, ge=1, le=10000)
    celery_result_expires_seconds: int = Field(3600, ge=60, le=604800)
    celery_result_backend_always_retry: bool = True
    celery_result_backend_max_retries: int = Field(5, ge=1, le=100)
    celery_worker_health_timeout_seconds: float = Field(2.0, ge=0.5, le=30.0)
    celery_worker_health_min_workers: int = Field(1, ge=1, le=100)
    celery_require_separate_redis_url: bool = False
    celery_dispatch_memory_soft_limit_mb: int = Field(1024, ge=128, le=262144)
    celery_dispatch_backpressure_step_seconds: int = Field(30, ge=0, le=1800)
    celery_dispatch_backpressure_max_seconds: int = Field(300, ge=0, le=7200)
    polite_delay_seconds: float = Field(1.0, ge=0.1, le=60.0)
    crawl_page_timeout_seconds: float = Field(30.0, ge=1.0, le=300.0)
    crawl_http_retry_max_attempts: int = Field(3, ge=1, le=10)
    crawl_http_retry_backoff_base_seconds: float = Field(0.5, ge=0.0, le=60.0)
    crawl_http_retry_backoff_max_seconds: float = Field(8.0, ge=0.1, le=300.0)
    crawl_retry_403_hosts: str = Field(
        "",
        description=(
            "Comma-separated hostnames that should retry HTTP 403 to handle host-specific WAF behavior."
        ),
    )
    crawl_upsert_chunk_size: int = Field(50, ge=1, le=1000)
    crawl_collect_sync_max_workers: int = Field(5, ge=1, le=32)
    crawl_collect_in_flight_limit: int = Field(500, ge=10, le=50000)
    crawl_max_links_per_run: int = Field(50_000, ge=100, le=500_000)
    crawl_collect_async_concurrency: int = Field(10, ge=1, le=200)
    crawl_seen_max_size: int = Field(10_000, ge=1_000, le=1_000_000)
    crawl_run_stale_seconds: float = Field(3600.0, ge=300.0, le=86400.0)

    # Content storage
    content_storage_type: str = "local"
    s3_bucket: str | None = None
    s3_region: str = "ap-northeast-2"
    s3_content_prefix: str = "notice-contents"
    s3_sse_kms_key_id: str | None = None
    content_storage_local_path: str = "storage/contents"
    content_storage_base_url: str = ""
    content_upload_failure_policy: str = "allow_none"
    content_spool_dir: str = Field(
        "storage/content_spool",
        description="Directory for failed upload spool.",
    )
    content_spool_backend: str = Field(
        "local",
        description="Spool backend. local | s3.",
    )
    content_spool_max_retries: int = Field(5, ge=1, le=20)
    content_spool_allow_ephemeral: bool = Field(
        False,
        description="Allow local ephemeral spool in production. Use only for emergency operation.",
    )
    content_spool_s3_prefix: str = Field(
        "content-spool",
        description="S3 prefix for spool entries.",
    )

    # Read cache
    read_cache_ttl_seconds: int = Field(60, ge=10, le=3600)
    read_cache_key_prefix: str = Field("read_cache:")
    read_cache_soft_ttl_seconds: int = Field(20, ge=5, le=3600)
    read_cache_lock_ttl_seconds: int = Field(10, ge=2, le=120)
    read_cache_wait_for_fresh_ms: int = Field(1000, ge=0, le=5000)

    # Crawl detail page read-through cache (scrape_*_detail only; list not cached)
    crawl_detail_cache_enabled: bool = Field(False, description="Enable read-through cache for detail HTML")
    crawl_detail_cache_ttl_seconds: int = Field(300, ge=60, le=3600)
    crawl_detail_cache_key_prefix: str = Field("dicee:crawl:detail:")

    # Degraded mode
    degraded_failure_threshold: int = Field(3, ge=1, le=20)
    degraded_recovery_success_count: int = Field(5, ge=1, le=50)

    # IP HMAC
    ip_hmac_key: SecretStr = SecretStr("")
    ip_hmac_key_version: str = "v1"

    # User ID HMAC (로깅·Sentry용 해시, 재식별 리스크 감소)
    user_id_hmac_key: SecretStr = SecretStr("")
    user_id_hmac_key_version: str = "v1"

    # CORS
    allowed_origins: str = ""

    def __getattribute__(self, name: str):
        if name in _LEGACY_CONFIG_FIELD_NAMES and is_legacy_config_forbidden():
            if not getattr(_legacy_guard_allow, "value", False):
                raise RuntimeError(
                    "LEGACY_CONFIG_FORBIDDEN: use settings.db.* / settings.redis.* instead of flat "
                    f"settings.{name}. Set LEGACY_CONFIG_FORBIDDEN=false or migrate the caller."
                )
        return object.__getattribute__(self, name)

    @field_validator(
        "database_url",
        "redis_url",
        "redis_celery_url",
        "s3_bucket",
        "content_storage_type",
        "allowed_origins",
        "jwt_secret",
        "google_client_secret",
        "gemini_api_key",
        "crawl_trigger_secret",
        mode="before",
    )
    @classmethod
    def strip_string_settings(cls, v: str | None) -> str | None:
        """Strip leading/trailing whitespace to avoid REDIS_URL='  url  ', JWT_SECRET='abc\\n' etc."""
        if v is None:
            return None
        if isinstance(v, str):
            return v.strip()
        if hasattr(v, "get_secret_value"):
            raw = v.get_secret_value()
            return (raw.strip() if raw else "") if isinstance(raw, str) else v
        return v

    @field_validator("jwt_signing_mode", mode="before")
    @classmethod
    def validate_jwt_signing_mode(cls, v: str | None) -> str:
        return normalize_jwt_signing_mode(v)

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, v: str | None) -> str:
        normalized = (v or "development").strip().lower()
        alias = {
            "prod": "production",
            "dev": "development",
        }
        return alias.get(normalized, normalized)

    @field_validator("allowed_origins", mode="after")
    @classmethod
    def validate_allowed_origins(cls, v: str) -> str:
        if not v or not v.strip():
            return v
        _parse_allowed_origins(v)
        return v

    @field_validator("database_url", mode="after")
    @classmethod
    def validate_database_url(cls, v: str | None) -> str | None:
        if not v:
            return v
        normalized = v.replace("postgres://", "postgresql://", 1) if v.startswith("postgres://") else v
        try:
            _POSTGRES_DSN_ADAPTER.validate_python(normalized)
        except Exception as exc:
            raise ValueError(
                "DATABASE_URL must use postgresql:// or postgresql+psycopg://. "
                "Runtime uses psycopg only (asyncpg URL is converted to psycopg)."
            ) from exc
        parsed = urlparse(normalized)
        if not parsed.hostname:
            raise ValueError("DATABASE_URL must include a hostname")
        return normalized

    @field_validator("redis_url", "redis_celery_url", mode="after")
    @classmethod
    def validate_redis_url(cls, v: str | None) -> str | None:
        if not v:
            return v
        normalized = v.strip()
        try:
            _REDIS_DSN_ADAPTER.validate_python(normalized)
        except Exception as exc:
            raise ValueError("REDIS_URL / REDIS_CELERY_URL must use redis:// or rediss://") from exc
        parsed = urlparse(normalized)
        if not parsed.hostname:
            raise ValueError("REDIS_URL / REDIS_CELERY_URL must include a hostname")
        return normalized

    @field_validator("content_storage_type", mode="after")
    @classmethod
    def validate_content_storage_type(cls, v: str) -> str:
        normalized = (v or "").strip().lower()
        if normalized not in {"local", "s3"}:
            raise ValueError("CONTENT_STORAGE_TYPE must be one of: local, s3")
        return normalized

    @field_validator("content_spool_backend", mode="after")
    @classmethod
    def validate_content_spool_backend(cls, v: str) -> str:
        normalized = (v or "").strip().lower()
        if normalized not in {"local", "s3"}:
            raise ValueError("CONTENT_SPOOL_BACKEND must be one of: local, s3")
        return normalized

    @field_validator("content_upload_failure_policy", mode="after")
    @classmethod
    def validate_content_upload_failure_policy(cls, v: str) -> str:
        normalized = (v or "").strip().lower()
        if normalized not in {"allow_none", "fail"}:
            raise ValueError("CONTENT_UPLOAD_FAILURE_POLICY must be one of: allow_none, fail")
        return normalized

    @property
    def allowed_origins_list(self) -> list[str]:
        return _parse_allowed_origins(self.allowed_origins)

    @property
    def trusted_proxy_ips_set(self) -> frozenset[str]:
        return frozenset(ip.strip() for ip in (self.trusted_proxy_ips or "").split(",") if ip.strip())

    @property
    def db(self) -> _DatabaseConfig:
        _legacy_guard_allow.value = True
        try:
            return _DatabaseConfig(
                database_url=self.database_url,
                db_connect_retries=self.db_connect_retries,
                db_connect_retry_interval_sec=self.db_connect_retry_interval_sec,
                strict_startup_db_check=self.strict_startup_db_check,
                db_pool_size_async=self.db_pool_size_async,
                db_pool_max_overflow_async=self.db_pool_max_overflow_async,
                db_pool_timeout_async=self.db_pool_timeout_async,
                db_pool_recycle_async=self.db_pool_recycle_async,
                db_statement_timeout_ms=self.db_statement_timeout_ms,
                db_pool_size_sync=self.db_pool_size_sync,
                db_pool_max_overflow_sync=self.db_pool_max_overflow_sync,
                db_pool_timeout_sync=self.db_pool_timeout_sync,
                db_pool_recycle_sync=self.db_pool_recycle_sync,
                db_max_connections=self.db_max_connections,
                db_reserved=self.db_reserved,
                db_pool_strict_budget=self.db_pool_strict_budget,
                deploy_surge_factor=self.deploy_surge_factor,
                db_api_instances=self.db_api_instances,
                db_uvicorn_workers=self.db_uvicorn_workers,
                db_worker_instances=self.db_worker_instances,
                db_celery_concurrency=self.db_celery_concurrency,
            )
        finally:
            _legacy_guard_allow.value = False

    @property
    def redis(self) -> _RedisConfig:
        _legacy_guard_allow.value = True
        try:
            return _RedisConfig(
                redis_url=self.redis_url,
                redis_ca_certs=self.redis_ca_certs,
                redis_socket_timeout=self.redis_socket_timeout,
                redis_socket_connect_timeout=self.redis_socket_connect_timeout,
                redis_blocklist_fail_closed=self.redis_blocklist_fail_closed,
                redis_blocklist_circuit_failure_threshold=self.redis_blocklist_circuit_failure_threshold,
                redis_blocklist_circuit_open_seconds=self.redis_blocklist_circuit_open_seconds,
                redis_blocklist_circuit_half_open_interval_seconds=self.redis_blocklist_circuit_half_open_interval_seconds,
                redis_blocklist_max_connections=self.redis_blocklist_max_connections,
                redis_trigger_lock_max_connections=self.redis_trigger_lock_max_connections,
                redis_trigger_lock_ttl_seconds=self.redis_trigger_lock_ttl_seconds,
                redis_trigger_lock_required=self.redis_trigger_lock_required,
                redis_trigger_idempotency_required=self.redis_trigger_idempotency_required,
                redis_crawl_seen_required=self.redis_crawl_seen_required,
            )
        finally:
            _legacy_guard_allow.value = False

    @model_validator(mode="after")
    def block_dev_using_production_db(self) -> "Settings":
        """development 환경에서 운영 DB 호스트로 접속하려 하면 기동 시 에러. 실수로 로컬에서 운영 DB 붙는 것 방지."""
        if (self.environment or "").strip().lower() not in {"development", "local", "test"}:
            return self
        raw = (self.database_url or "").strip()
        if not raw:
            return self
        try:
            # postgres:// vs postgresql:// 호환
            url = raw.replace("postgres://", "postgresql://", 1) if raw.startswith("postgres://") else raw
            parsed = urlparse(url)
            host = (parsed.hostname or parsed.netloc or "").lower()
            if not host or "@" in host:
                host = (parsed.netloc or "").split("@")[-1].split(":")[0].lower()
            # Railway 내부 호스트(*.railway.internal)는 Railway 네트워크 안에서만 연결 가능하므로,
            # 이 호스트가 보이면 이미 Railway 위에서 동작 중(배포 환경)으로 간주하고 검사 생략.
            if ".railway.internal" in host:
                return self

            # 운영/관리형 DB 호스트 패턴 (서브스트링 일치)
            production_indicators = (
                "rds.",
                ".rds.",
                "railway",
                ".railway",
                "supabase",
                "neon.tech",
                ".neon.",
            )
            for indicator in production_indicators:
                if indicator in host:
                    raise ValueError(
                        f"ENVIRONMENT=development but DATABASE_URL host looks like production "
                        f"({indicator!r} in {host!r}). Use a local DB or set ENVIRONMENT=production."
                    )
        except ValueError:
            raise
        except Exception:
            pass
        return self

    @model_validator(mode="after")
    def require_user_id_hmac_key_in_production(self) -> "Settings":
        """production 환경에서 USER_ID_HMAC_KEY 필수. 비어 있으면 부팅 실패(ValueError)."""
        if (self.environment or "").strip().lower() != "production":
            return self
        if self.app_entry == "migrate":
            return self
        raw = (self.user_id_hmac_key.get_secret_value() or "").strip()
        if not raw:
            raise ValueError(
                "Production environment requires USER_ID_HMAC_KEY to be set. "
                "Set USER_ID_HMAC_KEY in .env or Railway Variables."
            )
        return self

    @model_validator(mode="after")
    def read_cache_soft_ttl_lt_hard_ttl(self) -> "Settings":
        """read_cache: soft_ttl < hard_ttl 강제. wait_for_fresh_ms는 0 허용(즉시 fallback)."""
        if self.read_cache_soft_ttl_seconds >= self.read_cache_ttl_seconds:
            raise ValueError(
                "read_cache_soft_ttl_seconds must be less than read_cache_ttl_seconds. "
                f"Got soft={self.read_cache_soft_ttl_seconds}, hard={self.read_cache_ttl_seconds}."
            )
        return self

    @model_validator(mode="after")
    def fail_fast_s3_bucket_when_s3(self) -> "Settings":
        if (self.content_storage_type or "").strip().lower() == "s3" and not (self.s3_bucket or "").strip():
            raise ValueError(
                "content_storage_type is 's3' but S3_BUCKET is not set. "
                "Set S3_BUCKET or use content_storage_type=local."
            )
        return self

    @model_validator(mode="after")
    def validate_celery_redis_separation(self) -> "Settings":
        base = (self.redis_url or "").strip()
        celery = (self.redis_celery_url or "").strip()
        if not base or not celery:
            return self
        if base != celery:
            return self
        if self.celery_require_separate_redis_url:
            raise ValueError(
                "CELERY_REQUIRE_SEPARATE_REDIS_URL=true but REDIS_CELERY_URL equals REDIS_URL. "
                "Use a separate Redis DB/index or instance for Celery broker/result backend."
            )
        return self

    @model_validator(mode="after")
    def fail_fast_jwt_secret_at_boot(self) -> "Settings":
        if self.app_entry != "api":
            return self
        try:
            resolve_jwt_signing_algorithm(
                self.jwt_signing_mode,
                jwt_secret=self.jwt_secret.get_secret_value(),
                jwt_private_key_pem=(self.jwt_private_key_pem.get_secret_value() if self.jwt_private_key_pem else None),
                jwt_public_key_pem=(self.jwt_public_key_pem.get_secret_value() if self.jwt_public_key_pem else None),
            )
        except ValueError as e:
            raise ValueError(f"JWT signing configuration invalid: {e}") from e
        return self

    @model_validator(mode="after")
    def fail_fast_production(self) -> "Settings":
        if (self.environment or "").strip().lower() != "production":
            return self

        missing: list[str] = []

        if not (self.database_url or "").strip():
            missing.append("DATABASE_URL")

        if self.app_entry == "migrate":
            if missing:
                raise ValueError(
                    "Production environment requires these variables to be set: "
                    + ", ".join(missing)
                    + ". Set them in Secret Manager or environment before boot."
                )
            return self

        if not (self.redis_url or "").strip():
            missing.append("REDIS_URL")

        if self.app_entry != "celery":
            try:
                resolve_jwt_signing_algorithm(
                    self.jwt_signing_mode,
                    jwt_secret=self.jwt_secret.get_secret_value(),
                    jwt_private_key_pem=(
                        self.jwt_private_key_pem.get_secret_value() if self.jwt_private_key_pem else None
                    ),
                    jwt_public_key_pem=(
                        self.jwt_public_key_pem.get_secret_value() if self.jwt_public_key_pem else None
                    ),
                )
            except ValueError as e:
                missing.append(str(e))
            if not (self.ip_hmac_key.get_secret_value() or "").strip():
                missing.append("IP_HMAC_KEY")

        crawl_secret = self.crawl_trigger_secret.get_secret_value() if self.crawl_trigger_secret else ""
        if not (crawl_secret or "").strip():
            missing.append("CRAWL_TRIGGER_SECRET")

        policy = (self.content_upload_failure_policy or "").strip().lower()
        backend = (self.content_spool_backend or "").strip().lower()

        # Production: treat unset or default as 'fail' so deploy works without CONTENT_UPLOAD_FAILURE_POLICY.
        if policy in ("", "allow_none"):
            object.__setattr__(self, "content_upload_failure_policy", "fail")
            policy = "fail"
        elif policy != "fail":
            missing.append("CONTENT_UPLOAD_FAILURE_POLICY must be 'fail' in production (or unset)")

        # Production + local backend: require explicit CONTENT_SPOOL_ALLOW_EPHEMERAL=true (fail-fast).
        if policy == "fail" and backend == "local" and not self.content_spool_allow_ephemeral:
            missing.append(
                "CONTENT_SPOOL_ALLOW_EPHEMERAL must be 'true' in production when CONTENT_SPOOL_BACKEND=local "
                "(explicit allow only; do not auto-override)."
            )

        if not self.trusted_proxy_skip_fast and not (self.trusted_proxy_ips or "").strip():
            missing.append("TRUSTED_PROXY_IPS")

        # API only: production must use fail-closed for Redis blocklist (JWT invalidation).
        if self.app_entry == "api" and not self.redis_blocklist_fail_closed:
            missing.append("REDIS_BLOCKLIST_FAIL_CLOSED must be true in production when APP_ENTRY=api")

        # API only: trigger-crawl idempotency must fail-closed (RELEASE_GATE P0).
        if self.app_entry == "api" and not self.redis_trigger_idempotency_required:
            missing.append(
                "REDIS_TRIGGER_IDEMPOTENCY_REQUIRED must be true in production when APP_ENTRY=api"
            )

        has_google_client = bool(
            (self.google_client_id or "").strip() or (self.google_client_secret.get_secret_value() or "").strip()
        )
        if has_google_client:
            raw_uris = (self.google_redirect_uris or "").strip()
            if not raw_uris:
                missing.append("GOOGLE_REDIRECT_URIS")
            else:
                from urllib.parse import urlparse

                valid = False
                for raw_uri in raw_uris.split(","):
                    uri = raw_uri.strip()
                    if not uri:
                        continue
                    try:
                        parsed = urlparse(uri)
                        if parsed.scheme in ("http", "https") and parsed.netloc:
                            valid = True
                            break
                    except Exception:
                        continue
                if not valid:
                    missing.append("GOOGLE_REDIRECT_URIS(valid http(s) URL required)")

        if missing:
            raise ValueError(
                "Production environment requires these variables to be set: "
                + ", ".join(missing)
                + ". Set them in Secret Manager or environment before boot."
            )

        return self
