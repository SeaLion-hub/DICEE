"""환경 변수 공백 처리 및 설정 관련 회귀 테스트."""

import importlib

from app.core.config.base import Settings


def test_settings_strips_database_url_on_load(monkeypatch):
    """Settings 로드 시 database_url 앞뒤 공백이 strip 되어 저장된다."""
    monkeypatch.setenv("APP_ENTRY", "celery")
    s = Settings(database_url="  postgresql://localhost/mydb  ")  # type: ignore[reportCallIssue]
    assert s.database_url == "postgresql://localhost/mydb"


def test_settings_strips_redis_url_on_load(monkeypatch):
    """Settings 로드 시 redis_url 앞뒤 공백이 strip 되어 저장된다."""
    monkeypatch.setenv("APP_ENTRY", "celery")
    s = Settings(redis_url="  redis://localhost:6379/0  ")  # type: ignore[reportCallIssue]
    assert s.redis_url == "redis://localhost:6379/0"


def test_settings_strips_jwt_secret_on_load(monkeypatch):
    """Settings 로드 시 jwt_secret 앞뒤 공백·개행이 strip 되어 저장된다."""
    monkeypatch.setenv("APP_ENTRY", "celery")
    s = Settings(jwt_secret="  my-secret\n  ")  # type: ignore[reportCallIssue]
    assert s.jwt_secret.get_secret_value() == "my-secret"


def test_normalize_ssl_query_for_psycopg_replaces_ssl_with_sslmode(monkeypatch):
    """동기 엔진용 URL에서 ssl= 파라미터를 psycopg3 호환 sslmode= 로 변환한다."""
    monkeypatch.setenv("APP_ENTRY", "celery")
    from app.core.database_sync import _normalize_ssl_query_for_psycopg

    url = "postgresql://u:p@host/db?ssl=require"
    out = _normalize_ssl_query_for_psycopg(url)
    assert "sslmode=require" in out
    assert "ssl=" not in out

    url2 = "postgresql+psycopg://x@y/z?ssl=true&foo=bar"
    out2 = _normalize_ssl_query_for_psycopg(url2)
    assert "sslmode=require" in out2
    assert "foo=bar" in out2
    assert "ssl=" not in out2


def test_sync_database_url_treats_whitespace_as_unset(monkeypatch):
    """DATABASE_URL가 공백 문자열만 있을 때 _sync_database_url이 None을 반환한다."""
    from app.core import config, database_sync

    monkeypatch.setattr(config.settings, "database_url", "   ")
    # reload로 settings.database_url 변경 사항을 database_sync에 반영
    importlib.reload(database_sync)

    url = database_sync._sync_database_url()
    assert url is None


def test_worker_redis_url_whitespace_falls_back_to_default(monkeypatch):
    """REDIS_URL이 공백 문자열일 때 celery_app이 로컬 기본값으로 fallback한다."""
    monkeypatch.setenv("APP_ENTRY", "celery")
    import app.core.config as config_module

    importlib.reload(config_module)
    from app.core import config

    monkeypatch.setattr(config.settings, "redis_url", "   ")

    # settings.redis_url 패치 후 celery_app을 reload하여 broker_url 확인
    from app.core import celery_app as celery_app_module

    importlib.reload(celery_app_module)
    assert celery_app_module.broker_url == "redis://localhost:6379/0"
    assert celery_app_module.result_backend == "redis://localhost:6379/0"
