"""crawl_college_task Redis 실행 클레임: TTL·재전달 서사·renew EXPIRE."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def redis_url_for_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    # config 모듈이 다른 테스트에서 reload된 뒤에도 현재 싱글톤을 패치한다.
    from app.core.config import settings as live_settings

    monkeypatch.setattr(live_settings, "redis_url", "redis://127.0.0.1:6379/0")


def test_renew_crawl_task_execution_claim_calls_expire(redis_url_for_claim: None) -> None:
    from app.core import redis as redis_mod
    from app.core.redis import CRAWL_TASK_EXECUTION_CLAIM_KEY_PREFIX, renew_crawl_task_execution_claim

    client = MagicMock()
    client.expire.return_value = True
    task_id = "550e8400-e29b-41d4-a716-446655440000"
    expected_key = f"{CRAWL_TASK_EXECUTION_CLAIM_KEY_PREFIX}{task_id}"
    from app.core.config import settings as live_settings

    with patch.object(redis_mod, "_get_sync_redis_client", return_value=client):
        assert renew_crawl_task_execution_claim(task_id) is True

    client.expire.assert_called_once()
    assert client.expire.call_args[0][0] == expected_key
    assert client.expire.call_args[0][1] == int(live_settings.crawl_task_execution_claim_ttl_seconds)


def test_claim_redelivery_succeeds_after_key_cleared(redis_url_for_claim: None) -> None:
    """첫 SET NX 성공 → 동일 키로 재시도 시 중복 → 키 삭제 후 재시도 시 성공(브로커 재전달 서사)."""
    from app.core import redis as redis_mod
    from app.core.redis import claim_crawl_task_execution, release_crawl_task_execution

    client = MagicMock()
    client.set.side_effect = [True, False]
    task_id = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"

    with patch.object(redis_mod, "_get_sync_redis_client", return_value=client):
        assert claim_crawl_task_execution(task_id) is True
        assert claim_crawl_task_execution(task_id) is False
        release_crawl_task_execution(task_id)
        client.delete.assert_called_once()
        client.set.side_effect = [True]
        assert claim_crawl_task_execution(task_id) is True

    assert client.set.call_count == 3


def test_claim_uses_configured_ttl(redis_url_for_claim: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import redis as redis_mod
    from app.core.config import settings as live_settings
    from app.core.redis import claim_crawl_task_execution

    monkeypatch.setattr(live_settings, "crawl_task_execution_claim_ttl_seconds", 99)
    client = MagicMock()
    client.set.return_value = True

    with patch.object(redis_mod, "_get_sync_redis_client", return_value=client):
        assert claim_crawl_task_execution("550e8400-e29b-41d4-a716-446655440000") is True

    client.set.assert_called_once()
    _args, kwargs = client.set.call_args
    assert kwargs.get("nx") is True
    assert kwargs.get("ex") == 99
