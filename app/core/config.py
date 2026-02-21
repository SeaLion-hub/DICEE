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

    # 2단계 Auth (필수: 기본값 없음 → 부팅 시점 Fail-fast)
    jwt_secret: SecretStr
    jwt_issuer: str = "dicee"  # JWT iss 클레임 (발급자). 검증 시 사용.
    jwt_audience: str = "dicee-api"  # JWT aud 클레임 (대상). 검증 시 사용.
    jwt_access_expire_seconds: int = Field(600, ge=60, le=86400)  # Access 토큰 만료(초). 1분~24시간.
    jwt_refresh_expire_days: int = Field(7, ge=1, le=90)  # Refresh 토큰 만료(일).
    google_client_id: str  # 필수. 기본값 없음.
    google_client_secret: SecretStr  # 필수. 기본값 없음.
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

    # 6단계 CORS
    allowed_origins: str = ""

    @model_validator(mode="after")
    def fail_fast_production(self: "Settings") -> "Settings":
        """프로덕션 환경 시 필수 변수 누락이면 부팅 거부(Fail-Fast)."""
        if (self.environment or "").strip().lower() != "production":
            return self
        missing: list[str] = []
        if not (self.database_url or "").strip():
            missing.append("DATABASE_URL")
        if not (self.redis_url or "").strip():
            missing.append("REDIS_URL")
        if not (self.jwt_secret.get_secret_value() or "").strip():
            missing.append("JWT_SECRET")
        if not (self.google_client_id or "").strip():
            missing.append("GOOGLE_CLIENT_ID")
        if not (self.google_client_secret.get_secret_value() or "").strip():
            missing.append("GOOGLE_CLIENT_SECRET")
        if missing:
            raise ValueError(
                f"Production environment requires these variables to be set: {', '.join(missing)}. "
                "Set them in Secret Manager or environment before boot."
            )
        return self


settings = Settings()
