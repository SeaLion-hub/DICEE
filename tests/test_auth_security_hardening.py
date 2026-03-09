"""Auth 보안 강화 계획 검증: Fail-Closed, rollback, PII 로그, state replay, refresh reuse."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.metrics import REFRESH_TOKEN_REUSE_ATTEMPT_TOTAL, get_counter
from app.core.oauth_state import consume_state, store_state
from app.core.redis import BlocklistUnavailableError
from app.services.auth_service import AuthError, create_jwt_pair, verify_access_token
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_verify_access_token_fail_closed_redis_none_raises_blocklist_unavailable() -> None:
    """Phase 1: fail_closed=True이고 Redis가 None이면 BlocklistUnavailableError(503 변환)."""

    access_token, _ = create_jwt_pair(user_id=uuid.UUID("00000000-0000-7000-8000-000000000001"))
    with pytest.raises(BlocklistUnavailableError, match="Redis not configured"):
        await verify_access_token(
            access_token,
            redis_blocklist_client=None,
            fail_closed=True,
        )


@pytest.mark.asyncio
async def test_verify_access_token_fail_closed_redis_none_via_dep_returns_503(
    client: TestClient,
) -> None:
    """Phase 1: Bearer 검증 시 Redis None + fail_closed → 503."""
    from app.core.deps import get_redis_blocklist
    from app.main import app

    access_token, _ = create_jwt_pair(user_id=uuid.UUID("00000000-0000-7000-8000-000000000001"))

    async def _none_redis():
        return None

    app.dependency_overrides[get_redis_blocklist] = _none_redis
    with patch("app.api.v1.auth.settings") as mock_settings:
        mock_settings.redis.redis_blocklist_fail_closed = True
        resp = client.post(
            "/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    app.dependency_overrides.pop(get_redis_blocklist, None)
    assert resp.status_code == 503


def test_post_google_auth_rollback_on_unexpected_exception(client: TestClient) -> None:
    """Phase 2: post_google_auth에서 예상 외 예외 시 rollback 호출."""
    from app.core.database import get_db
    from app.main import app

    call_log: list[str] = []
    session = MagicMock()
    session.commit = AsyncMock(side_effect=lambda: call_log.append("commit"))
    session.rollback = AsyncMock(side_effect=lambda: call_log.append("rollback"))

    async def _get_db():
        yield session

    with patch("app.api.v1.auth.google_login", new_callable=AsyncMock) as mock_login:
        mock_login.side_effect = RuntimeError("injected")
        app.dependency_overrides[get_db] = _get_db
        try:
            try:
                resp = client.post(
                    "/v1/auth/google",
                    json={"code": "fake-code", "redirect_uri": "http://localhost"},
                )
                assert resp.status_code == 500
            except RuntimeError:
                pass
            assert "rollback" in call_log
            assert "commit" not in call_log
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_post_refresh_rollback_on_unexpected_exception(client: TestClient) -> None:
    """Phase 2: post_refresh에서 예상 외 예외 시 rollback 호출."""
    from app.core.database import get_db
    from app.main import app

    call_log: list[str] = []
    session = MagicMock()
    session.commit = AsyncMock(side_effect=lambda: call_log.append("commit"))
    session.rollback = AsyncMock(side_effect=lambda: call_log.append("rollback"))

    async def _get_db():
        yield session

    _, refresh_token = create_jwt_pair(user_id=uuid.UUID("00000000-0000-7000-8000-000000000001"))
    with patch("app.api.v1.auth.refresh_tokens", new_callable=AsyncMock) as mock_refresh:
        mock_refresh.side_effect = RuntimeError("injected")
        app.dependency_overrides[get_db] = _get_db
        try:
            try:
                resp = client.post(
                    "/v1/auth/refresh",
                    json={"refresh_token": refresh_token},
                )
                assert resp.status_code == 500
            except RuntimeError:
                pass
            assert "rollback" in call_log
            assert "commit" not in call_log
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_login_audit_failed_logs_user_id_hash_not_raw_uuid(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Phase 3: Login audit 실패 시 로그에 user_id_hash만 있고 raw user_id 없음. create_login_audit 호출 검증."""
    from app.services.auth_service import google_login

    user = MagicMock()
    user.id = uuid.UUID("00000000-0000-7000-8000-000000000002")
    user.refresh_token_version = 0
    mock_google_result = MagicMock(
        id_token="x",
        access_token="",
        token_type="Bearer",
        expires_in=3600,
        scope=None,
        refresh_token=None,
    )
    session = AsyncMock()
    with (
        patch("app.services.auth_service.upsert_by_provider_uid", new_callable=AsyncMock) as m_upsert,
        patch("app.services.auth_service.exchange_google_code", new_callable=AsyncMock) as m_ex,
        patch("app.services.auth_service.decode_google_id_token", new_callable=AsyncMock) as m_dec,
        patch("app.services.auth_service.create_login_audit", new_callable=AsyncMock) as m_audit,
    ):
        m_upsert.return_value = user
        m_ex.return_value = mock_google_result
        m_dec.return_value = {"sub": "google-123", "email": "a@b.com", "name": "Test"}
        m_audit.side_effect = Exception("audit fail")

        await google_login(
            session,
            "code",
            redirect_uri="http://localhost",
            http_client=MagicMock(),
            key_fetcher=MagicMock(),
            client_ip="127.0.0.1",
        )
        assert m_audit.called, "create_login_audit must be invoked for this test to be meaningful"

    log_text = caplog.text
    assert "00000000-0000-7000-8000-000000000002" not in log_text
    for record in caplog.records:
        assert "00000000-0000-7000-8000-000000000002" not in (record.message + str(getattr(record, "args", "")))


@pytest.mark.asyncio
async def test_oauth_state_consume_once_then_fail() -> None:
    """Phase 4: state 1회 소비 후 재사용 시 consume_state False."""

    class FakeRedis:
        def __init__(self):
            self._store = {}

        async def set(self, key: str, val: str, ex: int | None = None) -> bool:
            self._store[key] = val
            return True

        async def delete(self, key: str) -> int:
            return 1 if self._store.pop(key, None) is not None else 0

    fake = FakeRedis()
    state = "test-state-123"
    await store_state(fake, state)
    first = await consume_state(fake, state)
    assert first is True
    second = await consume_state(fake, state)
    assert second is False


def test_oauth_state_replay_returns_400(client: TestClient) -> None:
    """Phase 4: 동일 state로 두 번째 POST /google 시 400."""
    from app.core.deps import get_redis_blocklist
    from app.main import app

    class FakeRedis:
        def __init__(self):
            self._store = {}

        async def set(self, key: str, val: str, ex: int | None = None) -> bool:
            self._store[key] = val
            return True

        async def delete(self, key: str) -> int:
            return 1 if self._store.pop(key, None) is not None else 0

        async def get(self, key: str):
            return self._store.get(key)

    fake = FakeRedis()
    state_val = "replay-state-456"

    async def _get_fake_redis():
        return fake

    app.dependency_overrides[get_redis_blocklist] = _get_fake_redis
    import asyncio

    asyncio.get_event_loop().run_until_complete(store_state(fake, state_val))
    with patch("app.api.v1.auth.google_login", new_callable=AsyncMock) as mock_gl:
        from app.domain.contracts.auth_contracts import TokenResult

        mock_gl.return_value = TokenResult(
            access_token="at",
            refresh_token="rt",
            token_type="bearer",
            expires_in=600,
        )
        payload = {"code": "fake", "redirect_uri": "http://localhost", "state": state_val}
        r1 = client.post("/v1/auth/google", json=payload)
    assert r1.status_code == 200
    r2 = client.post("/v1/auth/google", json=payload)
    app.dependency_overrides.pop(get_redis_blocklist, None)
    assert r2.status_code == 400


def test_refresh_token_reuse_increments_metric() -> None:
    """Phase 5: 동일 refresh 재사용 시 REFRESH_TOKEN_REUSE_ATTEMPT_TOTAL 증가."""
    from app.services.auth_service import refresh_tokens
    from sqlalchemy.ext.asyncio import AsyncSession

    before = get_counter(REFRESH_TOKEN_REUSE_ATTEMPT_TOTAL)
    _, refresh_token = create_jwt_pair(
        user_id=uuid.UUID("00000000-0000-7000-8000-000000000003"),
        token_version=1,
    )

    async def _run():
        session = AsyncMock(spec=AsyncSession)
        with patch(
            "app.services.auth_service.rotate_refresh_token_version",
            new_callable=AsyncMock,
        ) as m_rot:
            m_rot.return_value = 2
            await refresh_tokens(refresh_token, session)
            m_rot.return_value = None
            with pytest.raises(AuthError):
                await refresh_tokens(refresh_token, session)

    import asyncio

    asyncio.get_event_loop().run_until_complete(_run())
    after = get_counter(REFRESH_TOKEN_REUSE_ATTEMPT_TOTAL)
    assert after == before + 1


def test_production_requires_state_for_google_auth(client: TestClient) -> None:
    """Production에서 POST /auth/google 시 state 누락하면 400 (CSRF 방어 우회 불가)."""
    with patch("app.api.v1.auth.settings.environment", "production"):
        resp = client.post(
            "/v1/auth/google",
            json={"code": "fake-code", "redirect_uri": "http://localhost"},
        )
    assert resp.status_code == 400
    assert "state" in (resp.json().get("detail") or "").lower()


def test_production_requires_user_id_hmac_key() -> None:
    """ENVIRONMENT=production에서 USER_ID_HMAC_KEY 누락 시 부팅 실패(ValueError). 정확한 실패 원인 검증."""
    env = {
        "ENVIRONMENT": "production",
        "APP_ENTRY": "api",
        "USER_ID_HMAC_KEY": "",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.core.config.base import Settings

        with pytest.raises(ValueError, match="Production environment requires USER_ID_HMAC_KEY"):
            Settings()  # type: ignore[reportCallIssue]
