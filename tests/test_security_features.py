"""보안 관련 기능 테스트: Rate Limit·내부 인증·오류 메시지 마스킹."""

import asyncio
import uuid

import pytest
from pydantic import SecretStr


def test_crawl_stats_masks_error_message(client, monkeypatch):
    """GET /internal/crawl-stats 응답에서 error_message는 제거되고 has_error만 노출된다."""
    from app.core.config import settings
    from app.core.database import get_db
    from app.main import app

    # 내부 트리거 시크릿 설정
    monkeypatch.setattr(settings, "crawl_trigger_secret", SecretStr("test-internal-secret"))

    # Repository 결과를 고정된 페이로드로 대체
    async def _fake_get_recent_crawl_runs(session, limit=50):
        return [
            {
                "college_code": "engineering",
                "started_at": "2024-01-01T00:00:00+00:00",
                "finished_at": None,
                "status": "FAILED",
                "notices_upserted": 0,
                "error_message": "simulated internal error detail",
            }
        ]

    monkeypatch.setattr("app.api.internal.get_recent_crawl_runs", _fake_get_recent_crawl_runs)

    # DB 의존성은 더미 세션으로 대체해, DATABASE_URL 없이도 테스트 가능하게 한다.
    async def _fake_get_db():
        class _DummySession:
            ...

        yield _DummySession()

    app.dependency_overrides[get_db] = _fake_get_db
    try:
        response = client.get(
            "/internal/crawl-stats",
            headers={"X-Crawl-Trigger-Secret": "test-internal-secret"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
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
    from app.core.database import get_db
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

    async def _fake_get_db():
        class _DummySession:
            ...

        yield _DummySession()

    app.dependency_overrides[get_db] = _fake_get_db
    try:
        response = client.get(
            "/internal/crawl-stats",
            headers={"X-Crawl-Trigger-Secret": "wrong-secret"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 401
    assert len(log_calls) == 1
    assert log_calls[0]["reason"] == "invalid_or_missing_secret"


def test_auth_google_rate_limit_returns_429(client, monkeypatch):
    """Rate limiter가 차단(True→False)일 때 /v1/auth/google이 429를 반환한다."""
    from app.api.v1 import auth as auth_module

    async def _deny_rate_limit(
        _client, *, identifier: str, max_requests: int, window_seconds: int, require_redis: bool = False, **kwargs: object
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


def test_get_client_ip_trusted_proxy_invalid_header_raises(monkeypatch):
    """신뢰 프록시 경유 시 X-Forwarded-For에 비IP 문자열이 있으면 InvalidForwardedHeaderError → 400."""
    from app.core.config import settings
    from app.core.network import InvalidForwardedHeaderError, get_client_ip

    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.1")

    class _Req:
        client = type("_C", (), {"host": "10.0.0.1"})()
        headers = {"x-forwarded-for": "10.0.0.1, not-an-ip"}

    with pytest.raises(InvalidForwardedHeaderError):
        get_client_ip(_Req())


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
    """InvalidForwardedHeaderError 발생 시 앱이 400 Bad Request를 반환한다."""
    from app.core.config import settings

    # Starlette TestClient 기본 client.host는 "testclient". trusted로 두고 잘못된 X-Forwarded-For 주입
    monkeypatch.setattr(settings, "trusted_proxy_ips", "testclient")

    response = client.post(
        "/v1/auth/google",
        json={"code": "x", "redirect_uri": "https://example.com/cb"},
        headers={"x-forwarded-for": "testclient, invalid-ip-here"},
    )
    assert response.status_code == 400
    data = response.json()
    assert data.get("code") == "INVALID_FORWARDED_HEADER"


def test_trigger_crawl_all_enqueues_fail_returns_503(client, monkeypatch):
    """POST /internal/trigger-crawl에서 enqueue가 전부 실패하면 503 + ALL_ENQUEUES_FAILED (P0 회귀 방지)."""
    from app.core.config import settings
    from app.core.database import get_db
    from app.core.deps import get_redis_trigger_lock
    from app.main import app
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "crawl_trigger_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "redis_trigger_lock_required", False)

    async def _fake_get_db():
        class _DummySession:
            pass
        yield _DummySession()

    async def _fake_redis():
        yield None

    app.dependency_overrides[get_db] = _fake_get_db
    app.dependency_overrides[get_redis_trigger_lock] = _fake_redis

    def _apply_async_raise(*args, **kwargs):
        raise RuntimeError("simulated broker failure")

    monkeypatch.setattr("app.services.tasks.crawl_college_task.apply_async", _apply_async_raise)

    try:
        response = client.post(
            "/internal/trigger-crawl",
            params={"college_code": "engineering"},
            headers={"X-Crawl-Trigger-Secret": "test-secret"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_redis_trigger_lock, None)
    assert response.status_code == 503
    data = response.json()
    assert data.get("code") == "ALL_ENQUEUES_FAILED" or "All crawl enqueues failed" in (data.get("detail") or "")


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


def test_check_crawl_trigger_secret_valid_and_invalid(monkeypatch):
    """check_crawl_trigger_secret가 올바른/잘못된 시크릿에 대해 예외를 올바르게 처리한다."""
    from app.core.config import settings
    from app.core.internal_auth import (
        CrawlTriggerNotConfiguredError,
        InvalidCrawlTriggerSecretError,
        check_crawl_trigger_secret,
    )

    # 설정 미구성 시 에러
    monkeypatch.setattr(settings, "crawl_trigger_secret", None)
    with pytest.raises(CrawlTriggerNotConfiguredError):
        check_crawl_trigger_secret("any", None)

    # 이후 테스트를 위해 시크릿 재설정
    monkeypatch.setattr(settings, "crawl_trigger_secret", SecretStr("test-secret"))

    # 올바른 시크릿은 통과
    check_crawl_trigger_secret("test-secret", None)

    # 잘못된 시크릿은 InvalidCrawlTriggerSecretError 발생
    with pytest.raises(InvalidCrawlTriggerSecretError):
        check_crawl_trigger_secret("wrong-secret", None)


def test_logout_blocklist_unavailable_returns_503(client, monkeypatch):
    """로그아웃 시 DB commit 후 Blocklist(Redis) 실패하면 503. DB는 이미 확정되어 재시도 시 Blocklist만 재등록."""
    from unittest.mock import AsyncMock, MagicMock

    from app.api.v1.auth import get_current_user_id_and_jti
    from app.core.database import get_db
    from app.core.deps import get_redis_blocklist
    from app.core.redis import BlocklistUnavailableError
    from app.main import app
    from fastapi import Request

    user_id = uuid.uuid4()
    jti = "test-jti"
    # 이 테스트 전용 호출 로그 — 동일 요청 경로에서 commit 선행 검증용.
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
        # 트랜잭션 순서: commit이 선행된 뒤 blocklist 실패로 503. 회귀 시 commit 미호출로 로그 비어 있음.
        assert "commit" in session_call_log, "logout must commit DB before attempting blocklist"
    finally:
        app.dependency_overrides.pop(get_current_user_id_and_jti, None)
        app.dependency_overrides.pop(get_redis_blocklist, None)
        app.dependency_overrides.pop(get_db, None)

