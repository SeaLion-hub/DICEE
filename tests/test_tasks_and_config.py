"""운영경로 테스트: Celery 태스크 등록, 예외 시 락 해제, production fail-fast."""

import importlib
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError


def test_crawl_college_task_is_celery_task_has_apply_async():
    """crawl_college_task가 Celery에 등록되어 apply_async를 갖는지 검증."""
    from app.services.tasks import crawl_college_task

    assert hasattr(crawl_college_task, "apply_async"), "crawl_college_task must be a Celery task with apply_async"
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


def test_crawl_college_task_duplicate_delivery_skips_execution():
    from app.services import tasks as tasks_module
    from app.services.tasks import crawl_college_task

    with (
        patch.object(tasks_module, "claim_crawl_task_execution", return_value=False) as mock_claim,
        patch.object(tasks_module, "run_crawl_job_sync") as mock_run,
        patch.object(tasks_module, "release_crawl_task_execution") as mock_release_exec,
        patch.object(tasks_module, "release_trigger_lock_sync") as mock_release_lock,
    ):
        result = crawl_college_task.apply(args=("engineering", "lock-token"), throw=True).result

    assert result == {"skipped": True, "reason": "duplicate_delivery"}
    assert mock_claim.called
    mock_run.assert_not_called()
    mock_release_exec.assert_not_called()
    mock_release_lock.assert_not_called()


def test_crawl_college_task_releases_execution_claim_in_finally():
    from app.services import tasks as tasks_module
    from app.services.tasks import crawl_college_task

    with (
        patch.object(tasks_module, "claim_crawl_task_execution", return_value=True),
        patch.object(tasks_module, "release_crawl_task_execution") as mock_release_exec,
        patch.object(tasks_module, "release_trigger_lock_sync"),
        patch.object(tasks_module, "get_sync_session") as mock_session,
        patch.object(tasks_module, "run_crawl_job_sync") as mock_run,
    ):
        mock_run.side_effect = RuntimeError("simulated crawl failure")
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_session.return_value = ctx

        with pytest.raises(RuntimeError, match="simulated crawl failure"):
            crawl_college_task.apply(args=("engineering", "lock-token"), throw=True)

    assert mock_release_exec.call_count == 1
    task_id = mock_release_exec.call_args[0][0]
    assert isinstance(task_id, str) and task_id


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
            "USER_ID_HMAC_KEY": "test-user-hmac",
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
            "USER_ID_HMAC_KEY": "test-user-hmac",
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


def test_validate_crawler_contract_fails_when_sync_callable_missing(monkeypatch):
    """Sync-only 계약: get_links 또는 scrape_detail 누락 시 fail-fast."""
    from app.core import crawler_config

    class _DummyCrawlerModule:
        @staticmethod
        def get_links(_list_url):
            return []

        # scrape_detail 누락

    def _fake_registry():
        return (
            {"dummy": "dummy_module"},
            {
                "dummy_module": {
                    "name": "Dummy",
                    "url": "https://example.com",
                    "get_links": "get_links",
                    "scrape_detail": "scrape_detail",
                }
            },
        )

    monkeypatch.setattr(crawler_config, "_ensure_registry", _fake_registry)
    monkeypatch.setattr(
        crawler_config.importlib,
        "import_module",
        lambda _name: _DummyCrawlerModule,
    )

    with pytest.raises(ValueError, match="missing required callables"):
        crawler_config.validate_crawler_contract()


def test_seed_colleges_match_crawler_registry_sorted():
    """자동 수집된 크롤러와 seed 소스가 일치하고, college_code 기준 정렬(deterministic)."""
    from app.core.crawler_config import COLLEGE_CODE_TO_MODULE, get_seed_colleges_from_crawlers

    seed_list = get_seed_colleges_from_crawlers()
    expected_codes = sorted(COLLEGE_CODE_TO_MODULE.keys())
    assert [code for _, code in seed_list] == expected_codes
    assert len(seed_list) == len(COLLEGE_CODE_TO_MODULE)


def test_production_local_spool_fail_fast_without_ephemeral_override():
    """Production + local spool + ALLOW_EPHEMERAL false: fail-fast. USER_ID_HMAC_KEY 포함해 spool 검증 실패만 보장."""
    import app.core.config as config_module

    with patch.dict(
        "os.environ",
        {
            "ENVIRONMENT": "production",
            "APP_ENTRY": "api",
            "DATABASE_URL": "postgresql://localhost/test",
            "REDIS_URL": "redis://localhost/0",
            "JWT_SIGNING_MODE": "hs256",
            "JWT_SECRET": "test-secret",
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
            "TRUSTED_PROXY_IPS": "10.0.0.1",
            "CRAWL_TRIGGER_SECRET": "test-trigger-secret",
            "USER_ID_HMAC_KEY": "test-user-hmac",
            "IP_HMAC_KEY": "test-ip-hmac-key",
            "CONTENT_UPLOAD_FAILURE_POLICY": "fail",
            "CONTENT_SPOOL_BACKEND": "local",
            "CONTENT_SPOOL_ALLOW_EPHEMERAL": "false",
        },
        clear=False,
    ):
        with pytest.raises((ValueError, ValidationError)) as exc_info:
            importlib.reload(config_module)
        assert "CONTENT_SPOOL_ALLOW_EPHEMERAL" in str(exc_info.value)
    importlib.reload(config_module)


def test_production_local_spool_allows_ephemeral_override():
    with patch.dict(
        "os.environ",
        {
            "ENVIRONMENT": "production",
            "APP_ENTRY": "api",
            "DATABASE_URL": "postgresql://localhost/test",
            "REDIS_URL": "redis://localhost/0",
            "JWT_SIGNING_MODE": "hs256",
            "JWT_SECRET": "test-secret",
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
            "TRUSTED_PROXY_IPS": "10.0.0.1",
            "CRAWL_TRIGGER_SECRET": "test-trigger-secret",
            "USER_ID_HMAC_KEY": "test-user-hmac",
            "IP_HMAC_KEY": "test-ip-hmac-key",
            "CONTENT_UPLOAD_FAILURE_POLICY": "fail",
            "CONTENT_SPOOL_BACKEND": "local",
            "CONTENT_SPOOL_ALLOW_EPHEMERAL": "true",
            "REDIS_BLOCKLIST_FAIL_CLOSED": "true",
        },
        clear=False,
    ):
        from app.core.config import Settings

        settings = Settings()
        assert settings.content_spool_allow_ephemeral is True


def test_non_production_local_spool_is_allowed():
    with patch.dict(
        "os.environ",
        {
            "ENVIRONMENT": "development",
            "APP_ENTRY": "api",
            "JWT_SIGNING_MODE": "hs256",
            "JWT_SECRET": "test-secret",
            "CONTENT_UPLOAD_FAILURE_POLICY": "fail",
            "CONTENT_SPOOL_BACKEND": "local",
            "CONTENT_SPOOL_ALLOW_EPHEMERAL": "false",
        },
        clear=False,
    ):
        from app.core.config import Settings

        settings = Settings()
        assert settings.environment == "development"


def test_settings_fail_fast_rs256_mode_requires_complete_keys():
    with patch.dict(
        "os.environ",
        {
            "APP_ENTRY": "api",
            "JWT_SIGNING_MODE": "rs256",
            "JWT_PRIVATE_KEY_PEM": "private-only",
            "JWT_PUBLIC_KEY_PEM": "",
            "JWT_SECRET": "",
        },
        clear=False,
    ):
        from app.core.config import Settings

        with pytest.raises(ValueError) as exc_info:
            Settings()
        assert "JWT_SIGNING_MODE=rs256" in str(exc_info.value)


def test_settings_fail_fast_hs256_mode_requires_secret():
    with patch.dict(
        "os.environ",
        {
            "APP_ENTRY": "api",
            "JWT_SIGNING_MODE": "hs256",
            "JWT_SECRET": "",
            "JWT_PRIVATE_KEY_PEM": "",
            "JWT_PUBLIC_KEY_PEM": "",
        },
        clear=False,
    ):
        from app.core.config import Settings

        with pytest.raises(ValueError) as exc_info:
            Settings()
        assert "JWT_SIGNING_MODE=hs256" in str(exc_info.value)


def test_config_package_import_smoke():
    import app.core.config as config_module
    from app.core.config import base as base_module

    assert config_module.settings is not None
    assert base_module.Settings is config_module.Settings


def test_settings_default_crawl_runtime_knobs():
    with patch.dict(
        "os.environ",
        {
            "ENVIRONMENT": "development",
            "APP_ENTRY": "api",
            "JWT_SIGNING_MODE": "hs256",
            "JWT_SECRET": "test-secret",
        },
        clear=False,
    ):
        from app.core.config import Settings

        cfg = Settings()
        assert cfg.crawl_page_timeout_seconds == 30.0
        assert cfg.crawl_upsert_chunk_size == 50
        assert cfg.crawl_collect_sync_max_workers == 5
        assert cfg.crawl_collect_in_flight_limit == 500
        assert cfg.crawl_max_links_per_run == 50_000
        assert cfg.crawl_collect_async_concurrency == 10


def test_settings_reject_invalid_crawl_runtime_knobs():
    with patch.dict(
        "os.environ",
        {
            "ENVIRONMENT": "development",
            "APP_ENTRY": "api",
            "JWT_SIGNING_MODE": "hs256",
            "JWT_SECRET": "test-secret",
            "CRAWL_COLLECT_IN_FLIGHT_LIMIT": "9",
        },
        clear=False,
    ):
        from app.core.config import Settings

        with pytest.raises(ValidationError):
            Settings()


def test_drain_content_spool_updates_retry_metadata_on_upload_failure(tmp_path, monkeypatch):
    from app.core import storage
    from app.services import tasks as tasks_module

    monkeypatch.setattr(tasks_module.settings, "content_spool_backend", "local")
    monkeypatch.setattr(tasks_module.settings, "content_spool_dir", str(tmp_path / "spool"))
    monkeypatch.setattr(tasks_module.settings, "content_spool_max_retries", 5)
    monkeypatch.setattr(storage.settings, "content_spool_backend", "local")
    monkeypatch.setattr(storage.settings, "content_spool_dir", str(tmp_path / "spool"))
    monkeypatch.setattr(storage.settings, "content_spool_max_retries", 5)

    storage._spool_write_failure(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "ext-1",
        "hash-1",
        "<html>hello</html>",
    )

    def _raise_upload(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks_module, "upload_notice_html", _raise_upload)

    result = tasks_module.drain_content_spool_task()
    assert result["drained"] == 0
    assert result["dlq"] == 0

    spool_files = sorted((tmp_path / "spool").glob("*.json"))
    assert len(spool_files) == 1
    payload = json.loads(spool_files[0].read_text(encoding="utf-8"))
    assert payload["retry_count"] == 1
    assert payload["last_error_type"] == "RuntimeError"
    assert payload["last_error_stage"] == "upload"


def test_drain_content_spool_moves_to_dlq_with_dead_letter_metadata(tmp_path, monkeypatch):
    from app.core import storage
    from app.services import tasks as tasks_module

    spool_dir = tmp_path / "spool"
    monkeypatch.setattr(tasks_module.settings, "content_spool_backend", "local")
    monkeypatch.setattr(tasks_module.settings, "content_spool_dir", str(spool_dir))
    monkeypatch.setattr(tasks_module.settings, "content_spool_max_retries", 1)
    monkeypatch.setattr(storage.settings, "content_spool_backend", "local")
    monkeypatch.setattr(storage.settings, "content_spool_dir", str(spool_dir))
    monkeypatch.setattr(storage.settings, "content_spool_max_retries", 1)

    storage._spool_write_failure(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "ext-1",
        "hash-1",
        "<html>hello</html>",
    )

    def _raise_upload(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks_module, "upload_notice_html", _raise_upload)

    result = tasks_module.drain_content_spool_task()
    assert result["dlq"] == 1
    assert result["failed"] == 1

    dlq_dir = Path(str(spool_dir) + "_dlq")
    dlq_files = sorted(dlq_dir.glob("*.json"))
    assert len(dlq_files) == 1
    payload = json.loads(dlq_files[0].read_text(encoding="utf-8"))
    assert payload["dead_letter_reason"] == "max_retries_exceeded"
    assert "dead_lettered_at" in payload
