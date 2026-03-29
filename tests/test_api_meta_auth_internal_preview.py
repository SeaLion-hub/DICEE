"""메타 옵션, Google OAuth state, internal engineering preview 라우트."""

import pytest
from fastapi import Request
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def _allow_auth_rate_limit_and_client_ip_for_google_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """google/state: IP 확정 + rate limit 통과(테스트 클라이언트는 XFF 없을 수 있음)."""

    async def _allow(*args: object, **kwargs: object) -> bool:
        return True

    from app.api.v1 import auth as auth_module

    monkeypatch.setattr(auth_module, "check_rate_limit", _allow)
    monkeypatch.setattr(auth_module, "get_client_ip", lambda _request: "127.0.0.1")


def test_list_department_options_returns_items(client) -> None:
    r = client.get("/v1/meta/department-options")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert len(data["items"]) >= 1
    first = data["items"][0]
    assert "code" in first and "label" in first


def test_list_grade_options_returns_all_target_grades(client) -> None:
    from app.domain.contracts.ai_extraction import TargetGrade

    r = client.get("/v1/meta/grade-options")
    assert r.status_code == 200
    data = r.json()
    values = {item["value"] for item in data["items"]}
    for g in TargetGrade:
        assert g.value in values


def test_google_auth_state_503_when_redis_unavailable(client) -> None:
    from app.core.deps import get_redis_blocklist
    from app.main import app

    def _redis_none(_request: Request) -> None:
        return None

    app.dependency_overrides[get_redis_blocklist] = _redis_none
    try:
        r = client.get("/v1/auth/google/state")
    finally:
        app.dependency_overrides.pop(get_redis_blocklist, None)

    assert r.status_code == 503
    assert "unavailable" in r.json()["detail"].lower()


def test_google_auth_state_503_when_store_fails(client) -> None:
    from app.core.deps import get_redis_blocklist
    from app.main import app

    class _RedisStoreFails:
        async def set(self, key: str, val: str, ex: int | None = None) -> bool:
            raise ConnectionError("simulated redis failure")

    def _redis_fail(_request: Request) -> _RedisStoreFails:
        return _RedisStoreFails()

    app.dependency_overrides[get_redis_blocklist] = _redis_fail
    try:
        r = client.get("/v1/auth/google/state")
    finally:
        app.dependency_overrides.pop(get_redis_blocklist, None)

    assert r.status_code == 503


def test_google_auth_state_200_returns_state(client) -> None:
    from app.core.deps import get_redis_blocklist
    from app.main import app

    class _OkRedis:
        async def set(self, key: str, val: str, ex: int | None = None) -> bool:
            return True

        async def eval(self, *args: object, **kwargs: object) -> int:
            return 1

    def _redis_ok(_request: Request) -> _OkRedis:
        return _OkRedis()

    app.dependency_overrides[get_redis_blocklist] = _redis_ok
    try:
        r = client.get("/v1/auth/google/state")
    finally:
        app.dependency_overrides.pop(get_redis_blocklist, None)

    assert r.status_code == 200
    body = r.json()
    assert "state" in body
    assert len(body["state"]) >= 8


def test_engineering_preview_200_with_secret_and_mock_service(client, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.internal_auth as internal_auth
    from app.core.config import settings
    from app.core.deps import get_notice_preview_service
    from app.main import app

    secret = SecretStr("preview-secret-test")
    monkeypatch.setattr(settings, "crawl_trigger_secret", secret)
    monkeypatch.setattr(internal_auth.settings, "crawl_trigger_secret", secret)

    class _FakePreview:
        async def get_engineering_preview(self, session: object, limit: int = 30) -> list:
            return []

    app.dependency_overrides[get_notice_preview_service] = lambda: _FakePreview()
    try:
        r = client.get(
            "/internal/preview/engineering",
            headers={"X-Crawl-Trigger-Secret": "preview-secret-test"},
        )
    finally:
        app.dependency_overrides.pop(get_notice_preview_service, None)

    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Engineering Crawl Preview" in r.text


def test_engineering_public_preview_404_in_production(client, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.internal as internal_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(internal_module.settings, "environment", "production")
    r = client.get("/internal/public-preview/engineering")
    assert r.status_code == 404


def test_engineering_public_preview_forbids_non_localhost_when_not_production(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.internal as internal_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(internal_module.settings, "environment", "development")
    r = client.get("/internal/public-preview/engineering")
    assert r.status_code == 403
    assert "localhost" in r.json()["detail"].lower()
