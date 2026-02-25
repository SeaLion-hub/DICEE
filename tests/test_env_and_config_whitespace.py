"""환경 변수 공백 처리 및 설정 관련 회귀 테스트."""

import importlib


def test_sync_database_url_treats_whitespace_as_unset(monkeypatch):
    """DATABASE_URL가 공백 문자열만 있을 때 _sync_database_url이 None을 반환한다."""
    from app.core import config
    from app.core import database_sync

    monkeypatch.setattr(config.settings, "database_url", "   ")
    # reload로 settings.database_url 변경 사항을 database_sync에 반영
    importlib.reload(database_sync)

    url = database_sync._sync_database_url()
    assert url is None


def test_worker_redis_url_whitespace_falls_back_to_default(monkeypatch):
    """REDIS_URL이 공백 문자열일 때 worker가 로컬 기본값으로 fallback한다."""
    from app.core import config

    monkeypatch.setattr(config.settings, "redis_url", "   ")

    # settings.redis_url 패치 후 worker를 import/reload하여 broker_url을 확인
    from app import worker as worker_module

    importlib.reload(worker_module)
    assert worker_module.broker_url == "redis://localhost:6379/0"
    assert worker_module.result_backend == "redis://localhost:6379/0"

