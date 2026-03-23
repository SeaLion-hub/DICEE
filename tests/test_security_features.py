"""보안 관련 기능 테스트: Rate Limit·내부 인증·오류 메시지 마스킹."""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from app.domain.contracts.crawl_contracts import CrawlRunRow
from pydantic import SecretStr


def test_crawl_stats_masks_error_message(client, monkeypatch):
    """GET /internal/crawl-stats 응답에서 error_message는 제거되고 has_error만 노출된다."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from app.api import internal as internal_module

    # 인증 우회: 이 테스트는 응답 마스킹만 검증
    def _noop_authorize(request, x_secret, auth):
        pass

    monkeypatch.setattr(internal_module, "_authorize_internal_trigger", _noop_authorize)
    # Soft TTL: miss + 락 획득으로 DB refresh 경로 타서 마스킹 검증
    monkeypatch.setattr(
        internal_module,
        "get_cached_with_soft_ttl",
        AsyncMock(return_value=(None, True, "lock-token")),
    )
    monkeypatch.setattr(internal_module, "set_cached_with_soft_ttl", AsyncMock())
    monkeypatch.setattr(internal_module, "release_cached_lock", AsyncMock())

    # 서비스가 호출하는 Repository 결과를 고정된 CrawlRunRow로 대체
    async def _fake_get_recent_crawl_runs(session, limit=50):
        return [
            CrawlRunRow(
                college_code="engineering",
                started_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),  # noqa: UP017
                finished_at=None,
                status="FAILED",
                notices_upserted=0,
                error_message="simulated internal error detail",
            )
        ]

    monkeypatch.setattr(
        "app.repositories.crawl_run_repository.get_recent_crawl_runs",
        _fake_get_recent_crawl_runs,
    )

    # get_crawl_stats는 세션을 Depends가 아닌 read_only_session_cm으로 지연 획득하므로, CM을 더미로 대체
    @asynccontextmanager
    async def _fake_read_only_session_cm(maker):
        class _DummySession: ...

        yield _DummySession()

    monkeypatch.setattr(internal_module, "read_only_session_cm", _fake_read_only_session_cm)
    response = client.get("/internal/crawl-stats")
    assert response.status_code == 200
    data = response.json()
    assert "runs" in data
    assert data["runs"]
    run = data["runs"][0]
    assert "error_message" not in run
    assert run["has_error"] is True


def test_crawl_stats_invalid_secret_logs_auth_failure(client, monkeypatch):
    """GET /internal/crawl-stats에 잘못된 시크릿으로 요청 시 _log_internal_auth_failure가 호출된다."""
    from app.api import internal as internal_module
    from app.core.config import settings
    from app.core.database import get_read_only_db
    from app.main import app

    monkeypatch.setattr(settings, "crawl_trigger_secret", SecretStr("correct-secret"))
    log_calls = []

    def _spy_log_internal_auth_failure(request, reason: str, error=None):
        log_calls.append({"reason": reason, "error": error})

    monkeypatch.setattr(
        internal_module,
        "_log_internal_auth_failure",
        _spy_log_internal_auth_failure,
    )

    async def _fake_get_read_only_db():
        class _DummySession: ...

        yield _DummySession()

    app.dependency_overrides[get_read_only_db] = _fake_get_read_only_db
    try:
        response = client.get(
            "/internal/crawl-stats",
            headers={"X-Crawl-Trigger-Secret": "wrong-secret"},
        )
    finally:
        app.dependency_overrides.pop(get_read_only_db, None)
    assert response.status_code == 401
    assert len(log_calls) == 1
    assert log_calls[0]["reason"] == "invalid_or_missing_secret"


def test_auth_google_rate_limit_returns_429(client, monkeypatch):
    """Rate limiter가 차단(True→False)일 때 /v1/auth/google이 429를 반환한다."""
    from app.api.v1 import auth as auth_module

    async def _deny_rate_limit(
        _client,
        *,
        identifier: str,
        max_requests: int,
        window_seconds: int,
        require_redis: bool = False,
        **kwargs: object,
    ) -> bool:
        return False

    # google_login이 호출되지 않도록 더미로 대체
    async def _dummy_google_login(*args, **kwargs):
        raise AssertionError("google_login should not be called when rate limited")

    monkeypatch.setattr(auth_module, "check_rate_limit", _deny_rate_limit)
    monkeypatch.setattr(auth_module, "google_login", _dummy_google_login)

    response = client.post(
        "/v1/auth/google",
        json={"code": "dummy-code", "redirect_uri": "https://example.com/callback"},
    )
    assert response.status_code == 429
    body = response.json()
    assert body["detail"].startswith("Too many")
    assert response.headers.get("retry-after") == "60"


def test_auth_refresh_rate_limit_returns_429(client, monkeypatch):
    """Rate limit 초과 시 /v1/auth/refresh가 429를 반환하고 refresh_tokens는 호출되지 않는다."""
    from app.api.v1 import auth as auth_module

    async def _deny_rate_limit(
        _client,
        *,
        identifier: str,
        max_requests: int,
        window_seconds: int,
        require_redis: bool = False,
        **kwargs: object,
    ) -> bool:
        return False

    async def _dummy_refresh_tokens(*args, **kwargs):
        raise AssertionError("refresh_tokens should not be called when rate limited")

    monkeypatch.setattr(auth_module, "check_rate_limit", _deny_rate_limit)
    monkeypatch.setattr(auth_module, "refresh_tokens", _dummy_refresh_tokens)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": "dummy-refresh-token"},
    )
    assert response.status_code == 429
    body = response.json()
    assert "Too many" in body["detail"] or "refresh" in body["detail"].lower()
    assert response.headers.get("retry-after") == "60"


def test_auth_refresh_rate_limit_fingerprint_returns_429(client, monkeypatch):
    """1차 IP 제한 통과 후 2차 token fingerprint 제한 초과 시 429를 반환한다."""
    from app.api.v1 import auth as auth_module

    seen_identifiers: list[str] = []

    async def _mixed_rate_limit(
        _client,
        *,
        identifier: str,
        max_requests: int,
        window_seconds: int,
        require_redis: bool = False,
        **kwargs: object,
    ) -> bool:
        seen_identifiers.append(identifier)
        if identifier.startswith("auth_refresh_fp:"):
            return False
        return True

    async def _dummy_refresh_tokens(*args, **kwargs):
        raise AssertionError("refresh_tokens should not be called when fingerprint rate limited")

    monkeypatch.setattr(auth_module, "check_rate_limit", _mixed_rate_limit)
    monkeypatch.setattr(auth_module, "refresh_tokens", _dummy_refresh_tokens)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": "dummy-refresh-token"},
    )
    assert response.status_code == 429
    body = response.json()
    assert "Too many" in body["detail"] or "refresh" in body["detail"].lower()
    assert response.headers.get("retry-after") == "60"
    fp_identifiers = [i for i in seen_identifiers if i.startswith("auth_refresh_fp:")]
    assert fp_identifiers, "fingerprint limiter identifier must be evaluated"
    assert all("testclient" not in i for i in fp_identifiers)


@pytest.mark.parametrize("raise_stage", ["ip", "fingerprint"])
def test_auth_refresh_rate_limit_unavailable_returns_503(client, monkeypatch, raise_stage):
    """1차 또는 2차 rate-limit 백엔드 장애 시 /v1/auth/refresh는 503을 반환한다."""
    from app.api.v1 import auth as auth_module
    from app.core.api_rate_limit import RateLimitUnavailableError

    async def _rate_limit_unavailable(
        _client,
        *,
        identifier: str,
        max_requests: int,
        window_seconds: int,
        require_redis: bool = False,
        **kwargs: object,
    ) -> bool:
        if raise_stage == "ip" and identifier.startswith("auth_refresh:"):
            raise RateLimitUnavailableError("simulated redis down on ip limiter")
        if raise_stage == "fingerprint" and identifier.startswith("auth_refresh_fp:"):
            raise RateLimitUnavailableError("simulated redis down on fingerprint limiter")
        return True

    async def _dummy_refresh_tokens(*args, **kwargs):
        raise AssertionError("refresh_tokens should not be called when rate limiter unavailable")

    monkeypatch.setattr(auth_module, "check_rate_limit", _rate_limit_unavailable)
    monkeypatch.setattr(auth_module, "refresh_tokens", _dummy_refresh_tokens)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": "dummy-refresh-token"},
    )
    assert response.status_code == 503
    assert "Rate limiting" in response.json().get("detail", "")


def test_auth_google_client_ip_unresolved_returns_400(client, monkeypatch):
    """/v1/auth/google에서 client IP를 결정할 수 없으면 503을 반환한다."""
    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module, "get_client_ip", lambda request: None)

    response = client.post(
        "/v1/auth/google",
        json={"code": "dummy-code", "redirect_uri": "https://example.com/callback"},
    )
    assert response.status_code == 400
    assert "Client IP" in response.json().get("detail", "")


def test_auth_refresh_client_ip_unresolved_returns_400(client, monkeypatch):
    """/v1/auth/refresh에서 client IP를 결정할 수 없으면 503을 반환한다."""
    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module, "get_client_ip", lambda request: None)

    response = client.post(
        "/v1/auth/refresh",
        json={"refresh_token": "dummy-refresh-token"},
    )
    assert response.status_code == 400
    assert "Client IP" in response.json().get("detail", "")


def test_check_rate_limit_inmemory_window(monkeypatch):
    """Redis 없는 환경에서 in-memory rate limit가 윈도우 내 횟수를 제한한다."""
    from app.core import api_rate_limit

    # 샤드별 상태 초기화 (샤드 락 + dict/heap 구조)
    n = api_rate_limit._NUM_SHARDS
    monkeypatch.setattr(api_rate_limit, "_shard_counts", [dict() for _ in range(n)])
    monkeypatch.setattr(api_rate_limit, "_shard_heaps", [list() for _ in range(n)])

    async def _run():
        results = []
        for _ in range(4):
            allowed = await api_rate_limit.check_rate_limit(
                None,
                identifier="test:ip-1",
                max_requests=3,
                window_seconds=60,
            )
            results.append(allowed)
        return results

    results = asyncio.run(_run())
    assert results == [True, True, True, False]


def test_get_client_ip_no_trusted_proxy_uses_client_host(monkeypatch):
    """직전 피어가 trusted가 아니면 X-Forwarded-For 무시하고 request.client.host 반환."""
    from app.core.config import settings
    from app.core.network import get_client_ip

    monkeypatch.setattr(settings, "trusted_proxy_ips", "")

    # client.host가 trusted에 없으면 항상 fallback
    class _Req:
        client = type("_C", (), {"host": "1.2.3.4"})()
        headers = {"x-forwarded-for": "10.0.0.1, 5.6.7.8"}

    assert get_client_ip(_Req()) == "1.2.3.4"


def test_get_client_ip_records_resolution_metrics(monkeypatch):
    from unittest.mock import MagicMock

    from app.core import metrics as metrics_module
    from app.core import network as network_module
    from app.core.network import get_client_ip
    from starlette.datastructures import Headers

    mock_settings = MagicMock()
    mock_settings.trusted_proxy_ips_set = frozenset({"10.0.0.1"})
    mock_settings.client_ip_resolution_log_sample_rate = 0.0
    monkeypatch.setattr(network_module, "settings", mock_settings)

    fallback_labels = {"mode": "fallback", "trusted_peer": "false"}
    xff_labels = {"mode": "xff", "trusted_peer": "true"}
    fallback_before = metrics_module.get_counter(metrics_module.CLIENT_IP_RESOLUTION_TOTAL, labels=fallback_labels)
    xff_before = metrics_module.get_counter(metrics_module.CLIENT_IP_RESOLUTION_TOTAL, labels=xff_labels)

    class _ReqFallback:
        client = type("_C", (), {"host": "1.2.3.4"})()
        headers = Headers({"x-forwarded-for": "8.8.8.8"})

    class _ReqXff:
        client = type("_C", (), {"host": "10.0.0.1"})()
        headers = Headers({"x-forwarded-for": "8.8.8.8,10.0.0.1"})

    assert get_client_ip(_ReqFallback()) == "1.2.3.4"
    assert get_client_ip(_ReqXff()) == "8.8.8.8"

    fallback_after = metrics_module.get_counter(metrics_module.CLIENT_IP_RESOLUTION_TOTAL, labels=fallback_labels)
    xff_after = metrics_module.get_counter(metrics_module.CLIENT_IP_RESOLUTION_TOTAL, labels=xff_labels)
    assert fallback_after == fallback_before + 1
    assert xff_after == xff_before + 1


def test_get_client_ip_trusted_proxy_invalid_header_raises(monkeypatch):
    """신뢰 프록시 경유 시 X-Forwarded-For에 비IP 문자열이 있으면 InvalidForwardedHeaderError → 400."""
    from unittest.mock import MagicMock  # noqa: I001

    from starlette.datastructures import Headers

    from app.core import metrics as metrics_module
    from app.core import network as network_module
    from app.core.network import InvalidForwardedHeaderError, get_client_ip

    # network가 참조하는 settings를 mock으로 교체해 trusted_proxy_ips_set = {10.0.0.1} 보장
    mock_settings = MagicMock()
    mock_settings.trusted_proxy_ips_set = frozenset({"10.0.0.1"})
    mock_settings.client_ip_resolution_log_sample_rate = 0.0
    monkeypatch.setattr(network_module, "settings", mock_settings)

    before = metrics_module.get_counter(metrics_module.INVALID_XFF_TOTAL)

    class _Req:
        client = type("_C", (), {"host": "10.0.0.1"})()
        headers = Headers({"x-forwarded-for": "10.0.0.1, not-an-ip"})

    with pytest.raises(InvalidForwardedHeaderError):
        get_client_ip(_Req())
    after = metrics_module.get_counter(metrics_module.INVALID_XFF_TOTAL)
    assert after == before + 1


def test_warn_trusted_proxy_configuration_logs_when_empty(monkeypatch, caplog):
    from app.core import network as network_module

    class _MockSettings:
        trusted_proxy_ips = ""

    monkeypatch.setattr(network_module, "settings", _MockSettings())
    with caplog.at_level("WARNING"):
        network_module.warn_trusted_proxy_configuration()
    assert "TRUSTED_PROXY_IPS is empty" in caplog.text


def test_request_id_sanitize_rejects_long_or_invalid_charset():
    """X-Request-ID: 길이 초과·비허용 문자면 새 UUID 사용 (P2 회귀 방지)."""
    from app.middleware.request_id import _sanitize_request_id

    bad = _sanitize_request_id("../../etc/passwd")
    assert bad != "../../etc/passwd"
    assert len(bad) == 36 and bad.count("-") == 4
    long_id = _sanitize_request_id("A" * 200)
    assert len(long_id) == 36
    valid = _sanitize_request_id("MyReq-123.ab:cd")
    assert valid == "MyReq-123.ab:cd"


def test_invalid_forwarded_header_returns_400(client, monkeypatch):
    """InvalidForwardedHeaderError 발생 시 앱이 400 Bad Request + code INVALID_FORWARDED_HEADER를 반환한다."""
    import asyncio  # noqa: I001
    import json
    from unittest.mock import MagicMock

    from fastapi import Request

    from app.core.exception_handlers import invalid_forwarded_header_handler
    from app.core.network import InvalidForwardedHeaderError

    # 핸들러 직접 호출로 응답 형식 검증 (경로/설정 의존 없음)
    req = MagicMock(spec=Request)
    req.state.request_id = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        resp = loop.run_until_complete(invalid_forwarded_header_handler(req, InvalidForwardedHeaderError("test")))
    finally:
        loop.close()
    assert resp.status_code == 400
    data = json.loads(resp.body)
    assert data.get("code") == "INVALID_FORWARDED_HEADER"
    assert "Invalid" in (data.get("detail") or "")


def test_trigger_crawl_all_enqueues_fail_returns_503(client, monkeypatch):
    """POST /internal/trigger-crawl에서 enqueue가 전부 실패하면 200 + ALL_ENQUEUES_FAILED (부분 실패 정책)."""
    from unittest.mock import AsyncMock, MagicMock

    from app.api import internal as internal_module
    from app.core.deps import get_redis_trigger_lock
    from app.main import app

    # 인증 우회: 이 테스트는 enqueue 실패 시 200 + 실패 코드 반환 검증
    def _noop_authorize(request, x_secret, auth):
        pass

    monkeypatch.setattr(internal_module, "_authorize_internal_trigger", _noop_authorize)

    # Redis 락 단계 통과용 mock (None이면 REDIS_LOCK_UNAVAILABLE 반환됨)
    _mock_redis = MagicMock()
    _mock_redis.set = AsyncMock(return_value=True)
    _mock_redis.get = AsyncMock(return_value=None)
    _mock_redis.delete = AsyncMock(return_value=1)

    async def _fake_redis():
        yield _mock_redis

    app.dependency_overrides[get_redis_trigger_lock] = _fake_redis

    def _apply_async_raise(*args, **kwargs):
        raise ConnectionError("simulated broker failure")

    monkeypatch.setattr("app.services.tasks.crawl_college_task.apply_async", _apply_async_raise)
    # InternalCrawlService가 사용하는 락 함수 패치
    monkeypatch.setattr(
        "app.services.internal_crawl_service.acquire_trigger_lock",
        AsyncMock(return_value=(True, "test-token")),
    )
    monkeypatch.setattr(
        "app.services.internal_crawl_service.release_trigger_lock",
        AsyncMock(return_value=None),
    )

    try:
        response = client.post(
            "/internal/trigger-crawl",
            params={"college_code": "engineering"},
        )
    finally:
        app.dependency_overrides.pop(get_redis_trigger_lock, None)
    assert response.status_code == 200
    data = response.json()
    assert data.get("code") == "ALL_ENQUEUES_FAILED"
    assert "failed" in data or "enqueued" in data


def test_trigger_crawl_skipped_then_retry_with_same_idempotency_key_not_stuck(client, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

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

    def _noop_authorize(request, x_secret, auth):
        pass

    async def _allow_rate_limit(*args, **kwargs):
        return True

    async def _fake_redis():
        yield mock_redis

    mock_redis = AsyncMockRedis()
    monkeypatch.setattr(internal_module, "_authorize_internal_trigger", _noop_authorize)
    monkeypatch.setattr(internal_module, "check_rate_limit", _allow_rate_limit)
    monkeypatch.setattr(internal_module, "get_client_ip", lambda request: "127.0.0.1")
    monkeypatch.setattr(
        "app.services.internal_crawl_service.acquire_trigger_lock",
        AsyncMock(side_effect=[(False, None), (True, "token-1")]),
    )
    monkeypatch.setattr(
        "app.services.internal_crawl_service.release_trigger_lock",
        AsyncMock(return_value=True),
    )

    task_result = MagicMock()
    task_result.id = "task-1"
    monkeypatch.setattr(
        "app.services.tasks.crawl_college_task.apply_async",
        lambda *args, **kwargs: task_result,
    )

    app.dependency_overrides[get_redis_trigger_lock] = _fake_redis
    try:
        headers = {"Idempotency-Key": "skip-then-retry-key"}
        first = client.post(
            "/internal/trigger-crawl",
            params={"college_code": "engineering"},
            headers=headers,
        )
        assert first.status_code == 200, first.json()
        assert "engineering" in first.json().get("skipped", [])

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


def test_trigger_crawl_invalid_secret_returns_401_before_rate_limit(client, monkeypatch):
    """POST /internal/trigger-crawl에 잘못된 시크릿이면 401 (rate-limit 소비 전 인증 실패, P1 회귀 방지)."""
    from app.core.config import settings
    from app.core.database import get_db
    from app.core.deps import get_redis_trigger_lock
    from app.main import app
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "crawl_trigger_secret", SecretStr("correct-secret"))
    monkeypatch.setattr(settings, "redis_trigger_lock_required", False)

    async def _fake_get_db():
        class _DummySession:
            pass

        yield _DummySession()

    async def _fake_redis():
        yield None

    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[get_redis_trigger_lock] = _fake_redis
    try:
        response = client.post(
            "/internal/trigger-crawl",
            params={"college_code": "engineering"},
            headers={"X-Crawl-Trigger-Secret": "wrong-secret"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_redis_trigger_lock, None)
    assert response.status_code == 401


def test_trigger_crawl_invalid_secret_repeated_hits_preauth_429(client, monkeypatch):
    """잘못된 시크릿 반복 호출 시 pre-auth limiter가 먼저 429를 반환한다."""
    from app.api import internal as internal_module
    from app.core.config import settings
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "crawl_trigger_secret", SecretStr("correct-secret"))
    counters: dict[str, int] = {}

    async def _fake_rate_limit(
        _client,
        *,
        identifier: str,
        max_requests: int,
        window_seconds: int,
        require_redis: bool = False,
        **kwargs: object,
    ) -> bool:
        if identifier.startswith("internal_preauth:/internal/trigger-crawl:"):
            counters[identifier] = counters.get(identifier, 0) + 1
            return counters[identifier] <= 2
        return True

    monkeypatch.setattr(internal_module, "check_rate_limit", _fake_rate_limit)

    headers = {"X-Crawl-Trigger-Secret": "wrong-secret"}
    first = client.post("/internal/trigger-crawl", params={"college_code": "engineering"}, headers=headers)
    second = client.post("/internal/trigger-crawl", params={"college_code": "engineering"}, headers=headers)
    third = client.post("/internal/trigger-crawl", params={"college_code": "engineering"}, headers=headers)

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429
    assert third.headers.get("retry-after") == "60"


def test_trigger_crawl_returns_503_when_client_ip_unresolved(client, monkeypatch):
    from app.api import internal as internal_module
    from app.core.deps import get_redis_trigger_lock
    from app.main import app

    def _noop_authorize(request, x_secret, auth):
        pass

    async def _allow_rate_limit(*args, **kwargs):
        return True

    async def _fake_redis():
        yield None

    monkeypatch.setattr(internal_module, "_authorize_internal_trigger", _noop_authorize)
    monkeypatch.setattr(internal_module, "get_client_ip", lambda request: None)
    monkeypatch.setattr(internal_module, "check_rate_limit", _allow_rate_limit)
    monkeypatch.setattr(internal_module.settings, "redis_trigger_lock_required", False)
    app.dependency_overrides[get_redis_trigger_lock] = _fake_redis
    try:
        response = client.post("/internal/trigger-crawl", params={"college_code": "engineering"})
    finally:
        app.dependency_overrides.pop(get_redis_trigger_lock, None)

    assert response.status_code == 503
    assert "Client IP could not be determined" in response.json().get("detail", "")


def test_check_crawl_trigger_secret_valid_and_invalid(monkeypatch):
    """check_crawl_trigger_secret가 올바른/잘못된 시크릿에 대해 예외를 올바르게 처리한다."""
    from unittest.mock import MagicMock

    from app.core import internal_auth as internal_auth_module
    from app.core.config import settings
    from app.core.internal_auth import (
        CrawlTriggerNotConfiguredError,
        InvalidCrawlTriggerSecretError,
        check_crawl_trigger_secret,
    )

    # 설정 미구성 시 에러: internal_auth가 참조하는 settings를 None 시크릿인 mock으로 일시 교체
    mock_settings = MagicMock()
    mock_settings.crawl_trigger_secret = None
    monkeypatch.setattr(internal_auth_module, "settings", mock_settings)
    with pytest.raises(CrawlTriggerNotConfiguredError):
        check_crawl_trigger_secret("any", None)

    # 이후 테스트를 위해 실제 settings로 복구 후 시크릿 설정
    monkeypatch.setattr(internal_auth_module, "settings", settings)
    monkeypatch.setattr(settings, "crawl_trigger_secret", SecretStr("test-secret"))

    # 올바른 시크릿은 통과
    check_crawl_trigger_secret("test-secret", None)

    # 잘못된 시크릿은 InvalidCrawlTriggerSecretError 발생
    with pytest.raises(InvalidCrawlTriggerSecretError):
        check_crawl_trigger_secret("wrong-secret", None)


def test_crawl_stats_returns_503_when_client_ip_unresolved(client, monkeypatch):
    from app.api import internal as internal_module
    from app.core.database import get_read_only_db
    from app.core.deps import get_redis_trigger_lock
    from app.main import app

    def _noop_authorize(request, x_secret, auth):
        pass

    async def _allow_rate_limit(*args, **kwargs):
        return True

    async def _fake_get_read_only_db():
        class _DummySession:
            pass

        yield _DummySession()

    async def _fake_redis():
        yield None

    monkeypatch.setattr(internal_module, "_authorize_internal_trigger", _noop_authorize)
    monkeypatch.setattr(internal_module, "get_client_ip", lambda request: None)
    monkeypatch.setattr(internal_module, "check_rate_limit", _allow_rate_limit)
    app.dependency_overrides[get_read_only_db] = _fake_get_read_only_db
    app.dependency_overrides[get_redis_trigger_lock] = _fake_redis
    try:
        response = client.get("/internal/crawl-stats")
    finally:
        app.dependency_overrides.pop(get_read_only_db, None)
        app.dependency_overrides.pop(get_redis_trigger_lock, None)

    assert response.status_code == 503
    assert "Client IP could not be determined" in response.json().get("detail", "")


def test_logout_blocklist_unavailable_returns_503(client, monkeypatch):
    """로그아웃 시 Redis Blocklist 먼저 시도. Blocklist 실패하면 503 반환하고 DB commit은 호출되지 않음."""
    from unittest.mock import AsyncMock, MagicMock

    from app.api.v1.auth import get_current_user_id_and_jti
    from app.core.database import get_db
    from app.core.deps import get_redis_blocklist
    from app.core.redis import BlocklistUnavailableError
    from app.main import app
    from fastapi import Request

    user_id = uuid.uuid4()
    jti = "test-jti"
    session_call_log: list[str] = []

    async def _fake_get_current_user_id_and_jti():
        return (user_id, jti)

    def _fake_get_redis_blocklist():
        return MagicMock()

    async def _get_db_tracking(request: Request):
        session_call_log.clear()
        session = MagicMock()
        session.commit = AsyncMock(side_effect=lambda: session_call_log.append("commit"))
        session.rollback = AsyncMock(side_effect=lambda: session_call_log.append("rollback"))
        session.execute = AsyncMock(return_value=None)
        yield session

    async def _noop_logout(session, user_id):
        return

    async def _add_access_raise_blocklist_unavailable(*args, **kwargs):
        raise BlocklistUnavailableError("Blocklist temporarily unavailable")

    from app.api.v1 import auth as auth_module

    app.dependency_overrides[get_current_user_id_and_jti] = _fake_get_current_user_id_and_jti
    app.dependency_overrides[get_redis_blocklist] = _fake_get_redis_blocklist
    app.dependency_overrides[get_db] = _get_db_tracking
    monkeypatch.setattr(auth_module, "logout_user", _noop_logout)
    monkeypatch.setattr(auth_module, "add_access_to_blocklist", _add_access_raise_blocklist_unavailable)
    try:
        response = client.post("/v1/auth/logout")
        assert response.status_code == 503
        data = response.json()
        assert "retry" in data.get("detail", "").lower()
        # Redis 먼저 순서: blocklist 실패 시 DB 로직(commit) 미호출.
        assert "commit" not in session_call_log, "logout must not commit DB when blocklist fails first"
    finally:
        app.dependency_overrides.pop(get_current_user_id_and_jti, None)
        app.dependency_overrides.pop(get_redis_blocklist, None)
        app.dependency_overrides.pop(get_db, None)
