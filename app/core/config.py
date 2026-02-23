"""환경 변수 기반 설정. pydantic-settings 사용."""

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # DB 풀 (용량 계획: DEPLOYMENT.md 참고). 미설정 시 아래 기본값 사용.
    db_pool_size_async: int = Field(5, ge=1, le=20, description="Async API 풀 크기(프로세스당).")
    db_pool_max_overflow_async: int = Field(10, ge=0, le=20, description="Async API 풀 오버플로(프로세스당).")
    db_pool_timeout_async: float = Field(30.0, ge=5.0, le=120.0, description="Async 풀 대기 타임아웃(초).")
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

    # 2단계 Auth (워커·Cron 등은 미설정 가능. production 시 validator에서 필수 검사)
    jwt_secret: SecretStr = SecretStr("")
    jwt_issuer: str = "dicee"  # JWT iss 클레임 (발급자). 검증 시 사용.
    jwt_audience: str = "dicee-api"  # JWT aud 클레임 (대상). 검증 시 사용.
    jwt_access_expire_seconds: int = Field(600, ge=60, le=86400)  # Access 토큰 만료(초). 1분~24시간.
    jwt_refresh_expire_days: int = Field(7, ge=1, le=90)  # Refresh 토큰 만료(일).
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    # 허용 redirect_uri 목록(쉼표 구분). 비어 있으면 검사 생략. 예: http://localhost:3000/callback,https://app.example.com/callback
    google_redirect_uris: str = ""

    # 3단계 Crawler & Worker (변수 추가)
    redis_url: str | None = None
    # rediss:// 사용 시 CA 번들 경로(선택). 미설정 시 시스템 기본 CA 사용.
    redis_ca_certs: str | None = None
    # Redis 소켓/연결 타임아웃(초). 풀 포화·장애 시 무한 대기 방지.
    redis_socket_timeout: float = Field(5.0, ge=1.0, le=60.0)
    redis_socket_connect_timeout: float = Field(2.0, ge=0.5, le=30.0)
    # Blocklist: Redis 장애 시 정책. True=Fail-Closed(인증 거부), False=Fail-Open(서명만 검증 후 통과).
    redis_blocklist_fail_closed: bool = True
    # Blocklist용 Redis 비동기 풀 크기. Uvicorn 워커 동시 처리량에 맞게 설정.
    redis_blocklist_max_connections: int = Field(20, ge=1, le=100)
    # Trigger 락용 Redis 비동기 풀 크기. 인증 풀과 분리해 장애 전파 완화(단일 Redis는 SPOF).
    redis_trigger_lock_max_connections: int = Field(5, ge=1, le=50)
    crawl_trigger_secret: SecretStr | None = None
    # 요청/페이지 간 최소 딜레이(초). 대상 서버 부하·IP 차단 완화용.
    polite_delay_seconds: float = Field(1.0, ge=0.1, le=60.0)

    # 본문 스토리지 (S3 또는 로컬). 명세: 본문은 DB가 아닌 오브젝트 스토리지, DB에는 content_url만.
    content_storage_type: str = "local"  # "s3" | "local"
    s3_bucket: str | None = None
    s3_region: str = "ap-northeast-2"
    s3_content_prefix: str = "notice-contents"
    # 로컬 스토리지 시 디렉터리 및 URL 접두사 (개발용)
    content_storage_local_path: str = "storage/contents"
    content_storage_base_url: str = ""  # 예: https://api.example.com/content

    # IP HMAC (명세 3.2): 평문 IP 저장 금지. DB에는 ip_hmac, ip_hmac_key_version만 저장.
    ip_hmac_key: SecretStr = SecretStr("")
    ip_hmac_key_version: str = "v1"

    # 6단계 CORS
    allowed_origins: str = ""

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
        if not (self.jwt_secret.get_secret_value() or "").strip():
            missing.append("JWT_SECRET")
        if missing:
            raise ValueError(
                f"Production environment requires these variables to be set: {', '.join(missing)}. "
                "Set them in Secret Manager or environment before boot."
            )
        return self


def check_pool_budget() -> tuple[bool, int, int]:
    """
    풀 예산 검사. DB_MAX_CONNECTIONS 미설정 시 검사 생략(True 반환).
    반환: (within_budget, peak_conn, app_budget).
    """
    max_conn = settings.db_max_connections
    if max_conn is None:
        return True, 0, 0
    api_conn = (
        settings.db_api_instances
        * settings.db_uvicorn_workers
        * (settings.db_pool_size_async + settings.db_pool_max_overflow_async)
    )
    worker_conn = (
        settings.db_worker_instances
        * settings.db_celery_concurrency
        * (settings.db_pool_size_sync + settings.db_pool_max_overflow_sync)
    )
    total = api_conn + worker_conn
    peak = int(total * settings.deploy_surge_factor)
    app_budget = int((max_conn - settings.db_reserved) * 0.7)
    return peak <= app_budget, peak, app_budget


settings = Settings()
