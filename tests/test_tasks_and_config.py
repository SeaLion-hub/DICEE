"""운영경로 테스트: Celery 태스크 등록, 예외 시 락 해제, production fail-fast."""

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
            "DATABASE_URL": "postgresql://localhost/test",
            "REDIS_URL": "redis://localhost/0",
            "JWT_SECRET": "test-secret",
            "IP_HMAC_KEY": "",
        },
        clear=False,
    ):
        from pydantic_settings import BaseSettings, SettingsConfigDict

        from app.core.config import Settings

        with pytest.raises(ValueError) as exc_info:
            Settings()
        assert "IP_HMAC_KEY" in str(exc_info.value)
