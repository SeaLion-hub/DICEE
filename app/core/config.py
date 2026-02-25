"""환경 변수 기반 설정. pydantic-settings 사용. 도메인별 그룹은 .db, .redis 등으로 노출(ADR: config-domain-split)."""

import json
import logging
from typing import NamedTuple

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class _DatabaseConfig(NamedTuple):
    """DB 관련 설정 뷰. settings.db.database_url 등으로 접근. 마이그레이션 후 구형 평탄화 접근은 금지(ADR)."""
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
    """Redis 관련 설정 뷰. settings.redis.redis_url 등으로 접근."""
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


def _parse_allowed_origins(value: str) -> list[str]:
    """JSON 배열만 파싱. ALLOWED_ORIGINS는 JSON 배열 형식만 지원. 예: [\"https://a.com\",\"https://b.com\"]"""
    if not value or not value.strip():
        return []
    s = value.strip()
    if not s.startswith("["):
        raise ValueError(
            "ALLOWED_ORIGINS must be a JSON array. Example: [\"https://example.com\"]"
        )
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"ALLOWED_ORIGINS invalid JSON: {e}") from e
    if not isinstance(parsed, list):
        raise ValueError("ALLOWED_ORIGINS must be a JSON array.")
    origins = [str(x).strip() for x in parsed if str(x).strip()]
    for o in origins:
        if o == "*":
            raise ValueError(
                "ALLOWED_ORIGINS cannot contain '*' when allow_credentials is True. "
                "Specify explicit origins as JSON array."
            )
        if not (o.startswith("http://") or o.startswith("https://")):
            raise ValueError(f"ALLOWED_ORIGINS entry must be http(s) URL: {o!r}")
    return origins


class Settings(BaseSettings):
    """앱 설정. 환경변수에서 로드. 시크릿은 SecretStr로 마스킹, 필수 시크릿은 기본값 없음(Fail-fast)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # 1단계 (선택)
    sentry_dsn: SecretStr | None = None
    environment: str = "development"  # Sentry/로깅용. production, staging, development 등.

    # 2단계~
    database_url: str | None = None
    db_connect_retries: int = Field(5, ge=1, le=20)  # 연결 실패 시 재시도 횟수.
    db_connect_retry_interval_sec: float = Field(2.0, ge=0.5, le=60.0)  # 재시도 간격(초).
    # DB 부팅 정책. True=연결 실패 시 부팅 중단, False=soft-start(기동은 하고 readiness에서 차단).
    strict_startup_db_check: bool = True

    # DB 풀 (용량 계획: DEPLOYMENT.md, 프로파일 R). 미설정 시 아래 기본값 사용.
    db_pool_size_async: int = Field(4, ge=1, le=20, description="Async API 풀 크기(프로세스당). 프로파일 R: 4.")
    db_pool_max_overflow_async: int = Field(6, ge=0, le=20, description="Async API 풀 오버플로(프로세스당). 프로파일 R: 6.")
    db_pool_timeout_async: float = Field(5.0, ge=1.0, le=120.0, description="Async 풀 대기 타임아웃(초). 운영 권장: 5.")
    # 쿼리 실행 제한(ms). 장기 쿼리가 풀을 잡고 늘어지는 것 방지. PostgreSQL statement_timeout.
    db_statement_timeout_ms: int = Field(30000, ge=1000, le=300000, description="Statement timeout(ms). 기본 30초.")
    db_pool_size_sync: int = Field(2, ge=1, le=10, description="Celery Sync 풀 크기(워커·자식당).")
    db_pool_max_overflow_sync: int = Field(0, ge=0, le=5, description="Celery Sync 풀 오버플로.")
    db_pool_timeout_sync: float = Field(30.0, ge=5.0, le=120.0, description="Sync 풀 대기 타임아웃(초).")
    db_pool_recycle_sync: int = Field(300, ge=-1, le=86400, description="Sync 풀 유휴 연결 재활용 주기(초). -1이면 미설정.")
    # 용량 검사용(선택). 설정 시 부팅 시 Peak_pool_conn vs App_budget 검사. DB_MAX_CONNECTIONS/DB_RESERVED.
    db_max_connections: int | None = Field(None, ge=1, le=1000, description="DB max_connections(검사용). 미설정 시 검사 생략.")
    db_reserved: int = Field(3, ge=0, le=20, description="DB 예약 연결 수(슈퍼유저/관리). App_budget=(max-Reserved)*0.7.")
    db_pool_strict_budget: bool = Field(False, description="True면 예산 초과 시 부팅 실패.")
    deploy_surge_factor: float = Field(2.0, ge=1.0, le=4.0, description="롤링/스케일 시 피크 배수. Peak=Total*이값.")
    # 예산 검사용(선택). DEPLOYMENT.md 용량 계획과 동일한 의미. 기본 1.
    db_api_instances: int = Field(1, ge=1, le=100, description="API 서비스 인스턴스 수(검사용).")
    db_uvicorn_workers: int = Field(1, ge=1, le=32, description="uvicorn 워커 수(검사용).")
    db_worker_instances: int = Field(1, ge=1, le=100, description="Celery 워커 인스턴스 수(검사용).")
    db_celery_concurrency: int = Field(1, ge=1, le=32, description="Celery concurrency(검사용, prefork 시 자식 수).")

    # X-Forwarded-For: 직전 피어가 이 목록에 있을 때만 X-Forwarded-For 헤더 신뢰. 쉼표 구분. 비어 있으면 항상 request.client.host만 사용.
    trusted_proxy_ips: str = ""

    # 2단계 Auth (워커·Cron 등은 미설정 가능. production 시 validator에서 필수 검사)
    jwt_secret: SecretStr = SecretStr("")
    # RS256: 둘 다 설정 시 RS256 사용(마이크로서비스 확장 시 검증 서비스는 Public Key만 보유). 미설정 시 JWT_SECRET으로 HS256.
    jwt_private_key_pem: SecretStr | None = None
    jwt_public_key_pem: SecretStr | None = None
    jwt_issuer: str = "dicee"  # JWT iss 클레임 (발급자). 검증 시 사용.
    jwt_audience: str = "dicee-api"  # JWT aud 클레임 (대상). 검증 시 사용.
    jwt_access_expire_seconds: int = Field(600, ge=60, le=86400)  # Access 토큰 만료(초). 1분~24시간.
    jwt_refresh_expire_days: int = Field(7, ge=1, le=90)  # Refresh 토큰 만료(일).
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    # 허용 redirect_uri 목록(쉼표 구분). 비어 있으면 검사 생략. 예: http://localhost:3000/callback,https://app.example.com/callback
    google_redirect_uris: str = ""

    # 인증·내부 API Rate Limit (분당 최대 호출 수)
    auth_google_rate_limit_per_minute: int = Field(
        10,
        ge=1,
        le=1000,
        description="동일 IP에 대한 /v1/auth/google 분당 최대 호출 수.",
    )
    auth_refresh_rate_limit_per_minute: int = Field(
        60,
        ge=1,
        le=5000,
        description="동일 IP에 대한 /v1/auth/refresh 분당 최대 호출 수.",
    )

    # 3단계 Crawler & Worker (변수 추가)
    redis_url: str | None = None
    # rediss:// 사용 시 CA 번들 경로(선택). 미설정 시 시스템 기본 CA 사용.
    redis_ca_certs: str | None = None
    # Redis 소켓/연결 타임아웃(초). 풀 포화·장애 시 무한 대기 방지.
    redis_socket_timeout: float = Field(5.0, ge=1.0, le=60.0)
    redis_socket_connect_timeout: float = Field(2.0, ge=0.5, le=30.0)
    # Blocklist: Redis 장애 시 정책. True=Fail-Closed(인증 거부), False=Fail-Open(서명만 검증 후 통과). 운영 권장 False(가용성 우선).
    redis_blocklist_fail_closed: bool = False
    # Blocklist Circuit Breaker: 연속 실패 N회 시 열림, open_seconds 동안 Fail-open.
    redis_blocklist_circuit_failure_threshold: int = Field(3, ge=1, le=50)
    redis_blocklist_circuit_open_seconds: float = Field(60.0, ge=5.0, le=300.0)
    redis_blocklist_circuit_half_open_interval_seconds: float = Field(15.0, ge=2.0, le=60.0)
    # Blocklist용 Redis 비동기 풀 크기. Uvicorn 워커 동시 처리량에 맞게 설정.
    redis_blocklist_max_connections: int = Field(20, ge=1, le=100)
    # Trigger 락용 Redis 비동기 풀 크기. 인증 풀과 분리해 장애 전파 완화(단일 Redis는 SPOF).
    redis_trigger_lock_max_connections: int = Field(5, ge=1, le=50)
    # TTL >= max_countdown + p99_runtime + safety. 단과대 7개·5분 스태거 시 max_countdown=1800 → 2400 권장.
    redis_trigger_lock_ttl_seconds: int = Field(2400, ge=60, le=86400)
    # True면 Redis 미설정/실패 시 락 없이 진행하지 않고 503. 운영 반영값 True.
    redis_trigger_lock_required: bool = True
    crawl_trigger_secret: SecretStr | None = None
    internal_trigger_crawl_rate_limit_per_minute: int = Field(
        10,
        ge=1,
        le=1000,
        description="동일 IP에 대한 /internal/trigger-crawl 분당 최대 호출 수.",
    )
    internal_crawl_stats_rate_limit_per_minute: int = Field(
        30,
        ge=1,
        le=1000,
        description="동일 IP에 대한 /internal/crawl-stats 분당 최대 호출 수.",
    )
    # True일 때만 AI 파이프라인(Gemini 등) 실행 및 done 저장. False면 process_notice_ai_task는 스킵(pending 유지).
    ai_pipeline_enabled: bool = False
    # Celery 워커 prefetch. 1=한 번에 하나만. 짧은 태스크 많으면 2~4로 올려 I/O 효율 개선. -O fair와 함께 사용.
    celery_worker_prefetch_multiplier: int = Field(1, ge=1, le=16, description="Worker prefetch multiplier. Use with -O fair.")
    # 요청/페이지 간 최소 딜레이(초). 대상 서버 부하·IP 차단 완화용.
    polite_delay_seconds: float = Field(1.0, ge=0.1, le=60.0)
    # Stale RUNNING 정리: started_at이 이 값(초)보다 오래된 RUNNING을 FAILED로 닫음. 크롤 최대 소요의 2~3배 권장.
    crawl_run_stale_seconds: float = Field(3600.0, ge=300.0, le=86400.0)

    # 본문 스토리지 (S3 또는 로컬). 명세: 본문은 DB가 아닌 오브젝트 스토리지, DB에는 content_url만.
    content_storage_type: str = "local"  # "s3" | "local"
    s3_bucket: str | None = None
    s3_region: str = "ap-northeast-2"
    s3_content_prefix: str = "notice-contents"
    # 로컬 스토리지 시 디렉터리 및 URL 접두사 (개발용)
    content_storage_local_path: str = "storage/contents"
    content_storage_base_url: str = ""  # 예: https://api.example.com/content
    # 업로드 실패 시: allow_none=None 반환(크롤 계속), fail=예외 전파(데이터 유실 방지).
    content_upload_failure_policy: str = "allow_none"  # "allow_none" | "fail"

    # IP HMAC (명세 3.2): 평문 IP 저장 금지. DB에는 ip_hmac, ip_hmac_key_version만 저장.
    ip_hmac_key: SecretStr = SecretStr("")
    ip_hmac_key_version: str = "v1"

    # 6단계 CORS (내부적으로 list[str] 사용. validator에서 CSV/JSON 둘 다 수용)
    allowed_origins: str = ""

    @model_validator(mode="after")
    def fail_fast_jwt_secret_at_boot(self: "Settings") -> "Settings":
        """JWT 시크릿 누락 시 부팅 시점에 즉시 크래시(Fail-Fast). 모든 환경 적용. '첫 JWT 사용 시점' 검사는 사용하지 않음."""
        has_jwt_secret = (self.jwt_secret.get_secret_value() or "").strip()
        has_rs256 = (
            self.jwt_private_key_pem
            and (self.jwt_private_key_pem.get_secret_value() or "").strip()
            and self.jwt_public_key_pem
            and (self.jwt_public_key_pem.get_secret_value() or "").strip()
        )
        if not has_jwt_secret and not has_rs256:
            raise ValueError(
                "JWT_SECRET or (JWT_PRIVATE_KEY_PEM + JWT_PUBLIC_KEY_PEM) must be set at boot. "
                "Secret key omission causes immediate crash (Fail-Fast). Set in environment or .env."
            )
        return self

    @model_validator(mode="after")
    def fail_fast_production(self: "Settings") -> "Settings":
        """프로덕션 환경 시 공통 필수 변수만 검사. JWT/Google은 워커에서 불필요하므로 여기서는 요구하지 않음."""
        if (self.environment or "").strip().lower() != "production":
            return self
        missing: list[str] = []
        if not (self.database_url or "").strip():
            missing.append("DATABASE_URL")
        if not (self.redis_url or "").strip():
            missing.append("REDIS_URL")
        has_jwt_secret = (self.jwt_secret.get_secret_value() or "").strip()
        has_rs256 = (
            self.jwt_private_key_pem
            and (self.jwt_private_key_pem.get_secret_value() or "").strip()
            and self.jwt_public_key_pem
            and (self.jwt_public_key_pem.get_secret_value() or "").strip()
        )
        if not has_jwt_secret and not has_rs256:
            missing.append("JWT_SECRET or (JWT_PRIVATE_KEY_PEM + JWT_PUBLIC_KEY_PEM)")
        if not (self.ip_hmac_key.get_secret_value() or "").strip():
            missing.append("IP_HMAC_KEY")
        if missing:
            raise ValueError(
                f"Production environment requires these variables to be set: {', '.join(missing)}. "
                "Set them in Secret Manager or environment before boot."
            )
        return self

    @property
    def allowed_origins_list(self) -> list[str]:
        """CORS 허용 오리진 리스트. JSON 배열만 지원. '*' 포함 시 ValueError(allow_credentials 사용 시)."""
        return _parse_allowed_origins(self.allowed_origins)

    @property
    def trusted_proxy_ips_set(self) -> frozenset[str]:
        """X-Forwarded-For 신뢰 시 사용할 직전 피어 IP 집합. 빈 문자열이면 빈 집합(헤더 미신뢰)."""
        return frozenset(
            ip.strip() for ip in (self.trusted_proxy_ips or "").split(",") if ip.strip()
        )

    @property
    def db(self) -> _DatabaseConfig:
        """DB 관련 설정 뷰. 마이그레이션 후 settings.db.* 만 사용(ADR config-domain-split)."""
        return _DatabaseConfig(
            database_url=self.database_url,
            db_connect_retries=self.db_connect_retries,
            db_connect_retry_interval_sec=self.db_connect_retry_interval_sec,
            strict_startup_db_check=self.strict_startup_db_check,
            db_pool_size_async=self.db_pool_size_async,
            db_pool_max_overflow_async=self.db_pool_max_overflow_async,
            db_pool_timeout_async=self.db_pool_timeout_async,
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

    @property
    def redis(self) -> _RedisConfig:
        """Redis 관련 설정 뷰. 마이그레이션 후 settings.redis.* 만 사용(ADR config-domain-split)."""
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
        )


def check_pool_budget(max_conn_override: int | None = None) -> tuple[bool, int, int]:
    """
    풀 예산 검사(프로파일 R 기준). max_conn_override 또는 DB_MAX_CONNECTIONS 사용.
    내부적으로 app.core.database.check_pool_budget 호출. 반환: (within_budget, peak_conn, app_budget).
    """
    from app.core.database import check_pool_budget as _check_pool_budget

    effective = (
        max_conn_override
        if max_conn_override is not None
        else settings.db_max_connections
    )
    r = _check_pool_budget(effective)
    return r.within_budget, r.peak_pool_conn, r.app_budget


settings = Settings()
