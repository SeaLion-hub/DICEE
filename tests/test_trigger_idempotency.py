"""Trigger-crawl Idempotency-Key 동작 검증."""

import asyncio
from unittest.mock import MagicMock

from app.core.redis import (
    IDEMPOTENCY_VALUE_IN_PROGRESS,
    get_trigger_idempotency_result,
    set_trigger_idempotency_result,
    try_claim_trigger_idempotency,
)


def test_try_claim_trigger_idempotency_atomic():
    """동일 키로 첫 요청만 점유 성공, 두 번째는 실패(원자적 처리)."""
    stored = {}

    class MockRedis:
        async def set(self, key, value, nx=False, ex=None):
            if nx and key in stored:
                return False
            stored[key] = value
            return True

    client = MockRedis()
    ok1 = asyncio.run(try_claim_trigger_idempotency(client, "idem-key-1", "all"))
    assert ok1 is True
    assert any(
        k.startswith("dicee:trigger_idempotency:") and stored[k] == IDEMPOTENCY_VALUE_IN_PROGRESS
        for k in stored
    )
    assert len(stored) == 1
    key = next(iter(stored))
    assert key.startswith("dicee:trigger_idempotency:") and len(key) > len("dicee:trigger_idempotency:") + 32

    ok2 = asyncio.run(try_claim_trigger_idempotency(client, "idem-key-1", "all"))
    assert ok2 is False


def test_get_set_trigger_idempotency_result_roundtrip():
    """Idempotency 결과 저장 후 조회 시 동일 dict 반환."""
    stored = {}

    class MockRedis:
        async def get(self, key):
            return stored.get(key)

        async def set(self, key, value, ex=None):
            stored[key] = value
            return True

    client = MockRedis()
    payload = {"enqueued": 2, "tasks": [{"college_code": "engineering", "task_id": "t1"}]}
    asyncio.run(set_trigger_idempotency_result(client, "key-1", "engineering", payload))
    assert any(k.startswith("dicee:trigger_idempotency:") for k in stored)
    assert len(stored) == 1
    out = asyncio.run(get_trigger_idempotency_result(client, "key-1", "engineering"))
    assert out == payload


def test_trigger_crawl_unknown_college_then_same_idempotency_key_succeeds(client, monkeypatch):
    """unknown college_code로 400 받은 뒤, 같은 Idempotency-Key로 유효한 college로 재요청 시 200(고착 없음)."""
    from app.core.config import settings
    from app.core.lifespan import create_app_state
    from pydantic import SecretStr

    class AsyncMockRedis:
        def __init__(self):
            self.stored = {}

        async def set(self, key, value, nx=False, ex=None):
            if nx and key in self.stored:
                return False
            self.stored[key] = value
            return True

        async def get(self, key):
            return self.stored.get(key)

    mock_redis = AsyncMockRedis()

    original_create_app_state = create_app_state

    def _create_app_state_with_mock_redis():
        state = original_create_app_state()
        state.redis_trigger_lock_client = mock_redis
        return state

    monkeypatch.setattr(settings, "crawl_trigger_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "redis_trigger_lock_required", False)
    monkeypatch.setattr("app.core.lifespan.create_app_state", _create_app_state_with_mock_redis)

    mock_result = MagicMock()
    mock_result.id = "task-1"
    monkeypatch.setattr(
        "app.services.tasks.crawl_college_task.apply_async",
        lambda *args, **kwargs: mock_result,
    )

    headers = {
        "X-Crawl-Trigger-Secret": "test-secret",
        "Idempotency-Key": "stucktestkey1",
    }

    r1 = client.post(
        "/internal/trigger-crawl",
        params={"college_code": "unknown_college_999"},
        headers=headers,
    )
    assert r1.status_code == 400, f"First request (unknown college) expected 400, got {r1.status_code}: {r1.json()}"
    assert "Unknown college_code" in str(r1.json().get("detail", ""))

    r2 = client.post(
        "/internal/trigger-crawl",
        params={"college_code": "engineering"},
        headers=headers,
    )
    assert r2.status_code == 200, f"Second request expected 200, got {r2.status_code}: {r2.json()}"
    data = r2.json()
    assert "enqueued" in data and data.get("enqueued", 0) >= 1
    assert data.get("detail") != "in_progress"
