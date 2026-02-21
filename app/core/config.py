"""환경 변수 기반 설정. pydantic-settings 사용."""

from pydantic import SecretStr, model_validator
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
    db_connect_retries: int = 5  # 연결 실패 시 재시도 횟수. 컨테이너 환경(Railway)용.
    db_connect_retry_interval_sec: float = 2.0  # 재시도 간격(초).

    # 2단계 Auth (필수: 기본값 없음 → 부팅 시점 Fail-fast)
    jwt_secret: SecretStr
    jwt_issuer: str = "dicee"  # JWT iss 클레임 (발급자). 검증 시 사용.
    jwt_audience: str = "dicee-api"  # JWT aud 클레임 (대상). 검증 시 사용.
    jwt_access_expire_seconds: int = 600  # Access 토큰 만료 (초). 기본 10분. 탈퇴/탈취 시 노출 시간 최소화.
    jwt_refresh_expire_days: int = 7  # Refresh 토큰 만료 (일). 기본 7일.
    google_client_id: str  # 필수. 기본값 없음.
    google_client_secret: SecretStr  # 필수. 기본값 없음.
    # 허용 redirect_uri 목록(쉼표 구분). 비어 있으면 검사 생략. 예: http://localhost:3000/callback,https://app.example.com/callback
    google_redirect_uris: str = ""

    # 3단계 Crawler & Worker (변수 추가)
    redis_url: str | None = None
    # Blocklist: Redis 장애 시 정책. True=Fail-Closed(인증 거부), False=Fail-Open(서명만 검증 후 통과).
    redis_blocklist_fail_closed: bool = True
    # Blocklist용 Redis 비동기 풀 크기. Uvicorn 워커 동시 처리량에 맞게 설정.
    redis_blocklist_max_connections: int = 20
    crawl_trigger_secret: SecretStr | None = None
    # 요청/페이지 간 최소 딜레이(초). 대상 서버 부하·IP 차단 완화용. 기본 1.
    polite_delay_seconds: int = 1

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
