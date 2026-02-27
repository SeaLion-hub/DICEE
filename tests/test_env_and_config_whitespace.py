"""환경 변수 공백 처리 및 설정 관련 회귀 테스트."""

import importlib


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

