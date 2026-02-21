"""환경 변수 기반 설정. pydantic-settings 사용."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱 설정. 환경변수에서 로드."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # 1단계
    sentry_dsn: str | None = None

    # 2단계~
    database_url: str | None = None
    db_connect_retries: int = 5  # 연결 실패 시 재시도 횟수. 컨테이너 환경(Railway)용.
    db_connect_retry_interval_sec: float = 2.0  # 재시도 간격(초).

    # 2단계 Auth
    jwt_secret: str = ""
    jwt_issuer: str = ""  # JWT iss 클레임 (발급자). 검증 시 사용.
    jwt_audience: str = ""  # JWT aud 클레임 (대상). 검증 시 사용.
    jwt_access_expire_seconds: int = 3600  # Access 토큰 만료 (초). 기본 1시간.
    jwt_refresh_expire_days: int = 7  # Refresh 토큰 만료 (일). 기본 7일.
    google_client_id: str = ""
    google_client_secret: str = ""

    # 3단계 Crawler & Worker (변수 추가)
    redis_url: str | None = None
    crawl_trigger_secret: str | None = None
    # 요청/페이지 간 최소 딜레이(초). 대상 서버 부하·IP 차단 완화용. 기본 1.
    polite_delay_seconds: int = 1

    # 6단계 CORS
    allowed_origins: str = ""


settings = Settings()
