"""운영경로 테스트: Celery 태스크 등록, 예외 시 락 해제, production fail-fast."""

import importlib
from unittest.mock import MagicMock, patch

import pytest


def test_crawl_college_task_is_celery_task_has_apply_async():
    """crawl_college_task가 Celery에 등록되어 apply_async를 갖는지 검증."""
    from app.services.tasks import crawl_college_task

    assert hasattr(crawl_college_task, "apply_async"), (
        "crawl_college_task must be a Celery task with apply_async"
    )
    assert callable(getattr(crawl_college_task, "apply_async", None))


def test_crawl_college_task_releases_lock_in_finally():
    """예외 발생 시에도 finally에서 release_trigger_lock_sync가 호출되는지 검증."""
    from app.services import tasks as tasks_module

    with patch.object(
        tasks_module, "release_trigger_lock_sync", wraps=tasks_module.release_trigger_lock_sync
    ) as mock_release:
        with patch.object(tasks_module, "get_sync_session") as mock_session:
            with patch.object(tasks_module, "run_crawl_job_sync") as mock_run:
                mock_run.side_effect = RuntimeError("simulated failure")
                ctx = MagicMock()
                ctx.__enter__ = MagicMock(return_value=ctx)
                ctx.__exit__ = MagicMock(return_value=False)
                mock_session.return_value = ctx

                from app.services.tasks import crawl_college_task

                with pytest.raises(RuntimeError):
                    crawl_college_task("engineering", "lock-token-12345")

                mock_release.assert_called()
                call_args = mock_release.call_args[0]
                assert call_args[0] == "engineering"
                assert call_args[1] == "lock-token-12345"


def test_production_fail_fast_requires_ip_hmac_key():
    """environment=production이고 IP_HMAC_KEY가 비어 있으면 Settings 로드 시 ValueError."""
    with patch.dict(
        "os.environ",
        {
            "ENVIRONMENT": "production",
            "APP_ENTRY": "api",
            "DATABASE_URL": "postgresql://localhost/test",
            "REDIS_URL": "redis://localhost/0",
            "JWT_SECRET": "test-secret",
            "TRUSTED_PROXY_IPS": "10.0.0.1",
            "CRAWL_TRIGGER_SECRET": "test-trigger-secret",
            "IP_HMAC_KEY": "",
        },
        clear=False,
    ):

        from app.core.config import Settings

        with pytest.raises(ValueError) as exc_info:
            Settings()
        assert "IP_HMAC_KEY" in str(exc_info.value)


def test_production_fail_fast_requires_trusted_proxy_ips():
    """prod 환경 + TRUSTED_PROXY_IPS 비어 있고 TRUSTED_PROXY_SKIP_FAST 미설정이면 ValidationError."""
    import app.core.config as config_module

    with patch.dict(
        "os.environ",
        {
            "ENVIRONMENT": "production",
            "APP_ENTRY": "api",
            "DATABASE_URL": "postgresql://localhost/test",
            "REDIS_URL": "redis://localhost/0",
            "JWT_SECRET": "test-secret",
            "TRUSTED_PROXY_IPS": "",
            "CRAWL_TRIGGER_SECRET": "test-trigger-secret",
            "IP_HMAC_KEY": "test-ip-hmac-key",
            "CONTENT_UPLOAD_FAILURE_POLICY": "fail",
        },
        clear=False,
    ):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            importlib.reload(config_module)
        assert "TRUSTED_PROXY_IPS" in str(exc_info.value)
    # Restore config module with normal env so later tests get valid settings
    importlib.reload(config_module)


def test_api_entry_fail_fast_when_app_entry_celery():
    """APP_ENTRY=celery일 때 app.main 로드 시 RuntimeError (API는 api 전용)."""
    import sys  # noqa: I001
    import app.core.config as config_module

    with patch.dict("os.environ", {"APP_ENTRY": "celery", "ROLE": "celery"}, clear=False):
        importlib.reload(config_module)
        main_module = sys.modules.get("app.main")
        with pytest.raises(RuntimeError) as exc_info:
            if main_module is not None:
                importlib.reload(main_module)
            else:
                importlib.import_module("app.main")
        assert "APP_ENTRY=api" in str(exc_info.value)
        assert "celery" in str(exc_info.value).lower()
    sys.modules.pop("app.main", None)
    with patch.dict("os.environ", {"APP_ENTRY": "celery"}, clear=False):
        importlib.reload(config_module)


def test_celery_entry_fail_fast_when_app_entry_api():
    """APP_ENTRY=api일 때 celery_app import는 성공(API에서 tasks import 가능). worker_init 시에만 RuntimeError."""
    import sys  # noqa: I001
    import app.core.config as config_module

    celery_app_module = sys.modules.pop("app.core.celery_app", None)
    try:
        with patch.dict("os.environ", {"APP_ENTRY": "api", "ROLE": "api"}, clear=False):
            importlib.reload(config_module)
            import app.core.celery_app as celery_app_mod
            # Import 시점에는 검사하지 않음 (API 프로세스에서 trigger-crawl enqueue 가능)
            assert celery_app_mod.app is not None
            # worker_init에서 호출되는 _ensure_celery_entry는 APP_ENTRY=api면 RuntimeError
            with pytest.raises(RuntimeError) as exc_info:
                celery_app_mod._ensure_celery_entry()
            assert "APP_ENTRY=celery" in str(exc_info.value)
            assert "api" in str(exc_info.value).lower()
    finally:
        if celery_app_module is not None:
            sys.modules["app.core.celery_app"] = celery_app_module
        with patch.dict("os.environ", {"APP_ENTRY": "celery"}, clear=False):
            importlib.reload(config_module)
