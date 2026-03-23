"""Trigger-crawl Idempotency-Key 동작 검증."""

import asyncio
from unittest.mock import MagicMock

from app.core.redis import (
    IDEMPOTENCY_VALUE_IN_PROGRESS,
    clear_trigger_idempotency_in_progress,
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
        k.startswith("dicee:trigger_idempotency:") and stored[k] == IDEMPOTENCY_VALUE_IN_PROGRESS for k in stored
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


def test_clear_trigger_idempotency_in_progress_deletes_only_in_progress():
    stored = {}

    class MockRedis:
        async def set(self, key, value, nx=False, ex=None):
            if nx and key in stored:
                return False
            stored[key] = value
            return True

        async def eval(self, script, numkeys, key, value):
            if stored.get(key) == value:
                del stored[key]
                return 1
            return 0

        async def get(self, key):
            return stored.get(key)

    client = MockRedis()
    key = "clear-test-key"
    scope = "engineering"

    claimed = asyncio.run(try_claim_trigger_idempotency(client, key, scope))
    assert claimed is True
    cleared = asyncio.run(clear_trigger_idempotency_in_progress(client, key, scope))
    assert cleared is True
    assert asyncio.run(get_trigger_idempotency_result(client, key, scope)) is None

    payload = {"enqueued": 1}
    asyncio.run(set_trigger_idempotency_result(client, key, scope, payload))
    cleared_again = asyncio.run(clear_trigger_idempotency_in_progress(client, key, scope))
    assert cleared_again is False
    assert asyncio.run(get_trigger_idempotency_result(client, key, scope)) == payload


async def _idempotency_get_raises(key):
    raise ConnectionError("redis down")


def test_idempotency_get_failure_logs_no_key_exposure(caplog):
    """get_trigger_idempotency_result 실패 시 로그에 idempotency key 또는 (key=) 미노출."""
    secret_key = "secret-idempotency-key-must-not-appear-in-logs"
    client = MagicMock()
    client.get = _idempotency_get_raises
    with caplog.at_level("WARNING"):
        result = asyncio.run(get_trigger_idempotency_result(client, secret_key, "scope"))
    assert result is None
    log_text = " ".join(r.message for r in caplog.records)
    assert secret_key not in log_text
    assert "(key=" not in log_text


async def _idempotency_set_raises(key, value, ex=None):
    raise OSError("redis set failed")


def test_idempotency_set_failure_logs_no_key_exposure(caplog):
    """set_trigger_idempotency_result 실패 시 로그에 idempotency key 또는 (key=) 미노출."""
    secret_key = "another-secret-key-not-in-logs"
    client = MagicMock()
    client.set = _idempotency_set_raises
    with caplog.at_level("WARNING"):
        asyncio.run(set_trigger_idempotency_result(client, secret_key, "scope", {"status": "ok"}))
    log_text = " ".join(r.message for r in caplog.records)
    assert secret_key not in log_text
    assert "(key=" not in log_text


def test_trigger_crawl_failed_enqueue_clears_idempotency_claim(client, monkeypatch):
    from unittest.mock import AsyncMock  # noqa: I001

    from fastapi import Request  # noqa: I001

    from app.api import internal as internal_module
    from app.core.deps import get_redis_trigger_lock
    from app.main import app

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

        async def eval(self, script, numkeys, key, value):
            if self.stored.get(key) == value:
                del self.stored[key]
                return 1
            return 0

    mock_redis = AsyncMockRedis()

    def _override_redis(request: Request):
        return mock_redis

    async def _allow_rate_limit(*args, **kwargs):
        return True

    monkeypatch.setattr(internal_module, "_authorize_internal_trigger", lambda *args, **kwargs: None)
    monkeypatch.setattr(internal_module, "check_rate_limit", _allow_rate_limit)
    monkeypatch.setattr(internal_module, "get_client_ip", lambda request: "127.0.0.1")
    monkeypatch.setattr(
        "app.services.internal_crawl_service.acquire_trigger_lock",
        AsyncMock(return_value=(True, "lock-token")),
    )
    monkeypatch.setattr(
        "app.services.internal_crawl_service.release_trigger_lock",
        AsyncMock(return_value=True),
    )
    app.dependency_overrides[get_redis_trigger_lock] = _override_redis

    call_count = {"n": 0}

    def _apply_async(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionError("broker down")
        out = MagicMock()
        out.id = "task-123"
        return out

    monkeypatch.setattr("app.services.tasks.crawl_college_task.apply_async", _apply_async)

    headers = {"Idempotency-Key": "retry-after-failure-key"}
    try:
        first = client.post(
            "/internal/trigger-crawl",
            params={"college_code": "engineering"},
            headers=headers,
        )
        assert first.status_code == 200, first.json()
        assert first.json().get("code") in ("ALL_ENQUEUES_FAILED", "PARTIAL_ENQUEUE_FAILURE")
        second = client.post(
            "/internal/trigger-crawl",
            params={"college_code": "engineering"},
            headers=headers,
        )
        assert second.status_code == 200, second.json()
        assert second.json().get("enqueued") == 1
        assert second.json().get("detail") != "in_progress"
    finally:
        app.dependency_overrides.pop(get_redis_trigger_lock, None)


def test_trigger_crawl_unknown_college_then_same_idempotency_key_succeeds(client, monkeypatch):
    """unknown college_code로 400 받은 뒤, 같은 Idempotency-Key로 유효한 college로 재요청 시 200(고착 없음)."""
    from fastapi import Request  # noqa: I001

    from app.core.config import settings
    from app.core.deps import get_redis_trigger_lock
    from app.main import app
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

        async def eval(self, script, numkeys, key, *args):
            # check_rate_limit: current count <= max_requests 이면 허용. 1 반환.
            # release_trigger_lock: 사용 시 1 반환(삭제됨).
            return 1

    mock_redis = AsyncMockRedis()

    def _override_redis(request: Request):
        return mock_redis

    monkeypatch.setattr(settings, "crawl_trigger_secret", SecretStr("test-secret"))
    monkeypatch.setattr("app.core.internal_auth.settings.crawl_trigger_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "redis_trigger_lock_required", False)
    app.dependency_overrides[get_redis_trigger_lock] = _override_redis

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

    try:
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
    finally:
        app.dependency_overrides.pop(get_redis_trigger_lock, None)


async def test_internal_crawl_idempotency_does_not_cache_when_skipped_only(monkeypatch):
    """enqueue 0·skipped만 있으면 멱등 결과를 저장하지 않아 동일 키 재시도가 가능하다."""
    from unittest.mock import AsyncMock

    from app.core.crawler_config import COLLEGE_CODE_TO_MODULE
    from app.domain.contracts.internal_contracts import TriggerCrawlCmd, TriggerCrawlResultKind
    from app.services import internal_crawl_service as ics
    from app.services.internal_crawl_service import InternalCrawlService

    code = next(iter(COLLEGE_CODE_TO_MODULE.keys()))

    class MockRedis:
        def __init__(self) -> None:
            self.stored: dict = {}

        async def set(self, key, value, nx=False, ex=None):
            if nx and key in self.stored:
                return False
            self.stored[key] = value
            return True

        async def get(self, key):
            return self.stored.get(key)

        async def eval(self, script, numkeys, key, value):
            if self.stored.get(key) == value:
                del self.stored[key]
                return 1
            return 0

    mock_redis = MockRedis()

    class Dispatcher:
        async def enqueue(self, college_code, lock_token, countdown, enqueued_at):
            return "tid"

    captured: list = []

    async def capture_set(redis, key, scope, payload):
        captured.append(payload)

    monkeypatch.setattr(ics, "try_claim_trigger_idempotency", AsyncMock(return_value=True))
    monkeypatch.setattr(ics, "acquire_trigger_lock", AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(ics, "release_trigger_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(ics, "set_trigger_idempotency_result", capture_set)
    monkeypatch.setattr(ics, "clear_trigger_idempotency_in_progress", AsyncMock(return_value=True))

    svc = InternalCrawlService(mock_redis, Dispatcher())
    cmd = TriggerCrawlCmd(college_code=code, idempotency_key="k-skip-cache", client_ip="127.0.0.1")
    result = await svc.trigger(cmd)
    assert result.result_kind == TriggerCrawlResultKind.success
    assert len(captured) == 0
    assert "skipped" in result.payload
