"""Auth Service 단위 테스트. DB/Google 호출 없이 검증."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from app.core.config import settings
from app.services.auth_service import (
    AuthError,
    _jwt_encode_key_and_algorithm,
    create_jwt_pair,
    decode_google_id_token,
    revoke_refresh_tokens_for_user,
    verify_refresh_token,
)
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


def test_create_jwt_pair_returns_two_tokens() -> None:
    """create_jwt_pair: JWT_SECRET 설정 시 access, refresh 두 토큰 반환."""
    user_uuid = uuid.UUID("00000000-0000-7000-8000-000000000001")
    access, refresh = create_jwt_pair(user_id=user_uuid)
    assert isinstance(access, str)
    assert isinstance(refresh, str)
    assert len(access) > 0
    assert len(refresh) > 0
    assert access != refresh


def test_create_jwt_pair_raises_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_jwt_pair: JWT_SECRET 비어 있으면 AuthError."""
    monkeypatch.setattr(
        "app.services.auth_service.settings.jwt_secret",
        SecretStr(""),
    )
    with pytest.raises(AuthError):
        create_jwt_pair(user_id=uuid.UUID("00000000-0000-7000-8000-000000000001"))


@pytest.mark.asyncio
async def test_decode_google_id_token_valid() -> None:
    """decode_google_id_token: key_fetcher.get_key + jwt.decode mock 시 claims 반환."""
    mock_fetcher = AsyncMock()
    mock_fetcher.get_key = AsyncMock(return_value={"key": "dummy-key-for-test"})
    with patch(
        "app.services.auth_service.jwt.decode",
        return_value={"sub": "123", "email": "a@b.com", "name": "Test"},
    ):
        result = await decode_google_id_token("fake-id-token", mock_fetcher)
        assert result["sub"] == "123"
        assert result["email"] == "a@b.com"


def test_allowed_redirect_uris_raises_when_config_set_but_all_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """_allowed_redirect_uris: 설정값은 있으나 유효 URI 없으면 AuthError (P0 fail-closed 회귀 방지)."""
    from app.services.auth_service import AuthError, _allowed_redirect_uris

    monkeypatch.setattr("app.services.auth_service.settings.google_redirect_uris", "http://invalid??,not-a-uri")
    _allowed_redirect_uris.cache_clear()
    try:
        with pytest.raises(AuthError, match="google_redirect_uris.*no valid"):
            _allowed_redirect_uris()
    finally:
        _allowed_redirect_uris.cache_clear()


def test_jwt_auto_prefers_rs_when_hs_and_rs_both_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.auth_service.settings.jwt_signing_mode", "auto")
    monkeypatch.setattr("app.services.auth_service.settings.jwt_secret", SecretStr("hs-secret"))
    monkeypatch.setattr("app.services.auth_service.settings.jwt_private_key_pem", SecretStr("private-key"))
    monkeypatch.setattr("app.services.auth_service.settings.jwt_public_key_pem", SecretStr("public-key"))

    with patch("app.services.auth_service.jwt.encode", return_value="token") as mock_encode:
        create_jwt_pair(user_id=uuid.UUID("00000000-0000-7000-8000-000000000001"))

    assert mock_encode.call_count == 2
    assert all(call.kwargs["algorithm"] == "RS256" for call in mock_encode.call_args_list)


def test_jwt_auto_falls_back_to_hs_when_rs_keypair_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.auth_service.settings.jwt_signing_mode", "auto")
    monkeypatch.setattr("app.services.auth_service.settings.jwt_secret", SecretStr("hs-secret"))
    monkeypatch.setattr("app.services.auth_service.settings.jwt_private_key_pem", SecretStr(""))
    monkeypatch.setattr("app.services.auth_service.settings.jwt_public_key_pem", SecretStr("public-key-only"))

    with patch("app.services.auth_service.jwt.encode", return_value="token") as mock_encode:
        create_jwt_pair(user_id=uuid.UUID("00000000-0000-7000-8000-000000000001"))

    assert mock_encode.call_count == 2
    assert all(call.kwargs["algorithm"] == "HS256" for call in mock_encode.call_args_list)


def test_jwt_rs256_mode_requires_complete_keypair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.auth_service.settings.jwt_signing_mode", "rs256")
    monkeypatch.setattr("app.services.auth_service.settings.jwt_secret", SecretStr("hs-secret"))
    monkeypatch.setattr("app.services.auth_service.settings.jwt_private_key_pem", SecretStr("private-only"))
    monkeypatch.setattr("app.services.auth_service.settings.jwt_public_key_pem", None)

    with pytest.raises(AuthError, match="JWT_SIGNING_MODE=rs256"):
        create_jwt_pair(user_id=uuid.UUID("00000000-0000-7000-8000-000000000001"))


def test_jwt_hs256_mode_requires_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.auth_service.settings.jwt_signing_mode", "hs256")
    monkeypatch.setattr("app.services.auth_service.settings.jwt_secret", SecretStr(""))
    monkeypatch.setattr("app.services.auth_service.settings.jwt_private_key_pem", SecretStr("private"))
    monkeypatch.setattr("app.services.auth_service.settings.jwt_public_key_pem", SecretStr("public"))

    with pytest.raises(AuthError, match="JWT_SIGNING_MODE=hs256"):
        create_jwt_pair(user_id=uuid.UUID("00000000-0000-7000-8000-000000000001"))


def test_encode_decode_use_same_mode_in_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.auth_service import (
        _jwt_decode_key_and_algorithm,
        _jwt_encode_key_and_algorithm,
    )

    monkeypatch.setattr("app.services.auth_service.settings.jwt_signing_mode", "auto")
    monkeypatch.setattr("app.services.auth_service.settings.jwt_secret", SecretStr("hs-secret"))
    monkeypatch.setattr("app.services.auth_service.settings.jwt_private_key_pem", None)
    monkeypatch.setattr("app.services.auth_service.settings.jwt_public_key_pem", SecretStr("public-only"))

    _, encode_alg = _jwt_encode_key_and_algorithm()
    _, decode_alg = _jwt_decode_key_and_algorithm()
    assert encode_alg == "HS256"
    assert decode_alg == "HS256"


def test_verify_refresh_token_accepts_valid_pair() -> None:
    uid = uuid.UUID("00000000-0000-7000-8000-000000000010")
    _, refresh = create_jwt_pair(user_id=uid, token_version=2)
    payload = verify_refresh_token(refresh)
    assert payload["type"] == "refresh"
    assert payload["sub"] == str(uid)
    assert int(payload["token_version"]) == 2


def test_verify_refresh_token_rejects_non_refresh_type() -> None:
    """type=access인 토큰은 디코드는 되어도 refresh 검증에서 거부된다."""
    key, algorithm = _jwt_encode_key_and_algorithm()
    now = datetime.now(UTC)
    uid = uuid.UUID("00000000-0000-7000-8000-000000000011")
    payload = {
        "sub": str(uid),
        "type": "access",
        "jti": str(uuid.uuid4()),
        "token_version": 0,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": now + timedelta(days=1),
        "iat": now,
        "nbf": now,
    }
    token = jwt.encode(payload, key, algorithm=algorithm)
    with pytest.raises(AuthError, match="Invalid token type"):
        verify_refresh_token(token)


def test_verify_refresh_token_rejects_expired() -> None:
    key, algorithm = _jwt_encode_key_and_algorithm()
    now = datetime.now(UTC)
    uid = uuid.UUID("00000000-0000-7000-8000-000000000012")
    payload = {
        "sub": str(uid),
        "type": "refresh",
        "token_version": 0,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": now - timedelta(hours=1),
        "iat": now - timedelta(hours=2),
        "nbf": now - timedelta(hours=2),
    }
    token = jwt.encode(payload, key, algorithm=algorithm)
    with pytest.raises(AuthError, match="Invalid or expired refresh token"):
        verify_refresh_token(token)


@pytest.mark.asyncio
async def test_revoke_refresh_tokens_for_user_awaits_increment() -> None:
    uid = uuid.UUID("00000000-0000-7000-8000-000000000013")
    session = AsyncMock(spec=AsyncSession)
    with patch(
        "app.services.auth_service.increment_refresh_token_version",
        new_callable=AsyncMock,
    ) as m_inc:
        await revoke_refresh_tokens_for_user(session, uid)
        m_inc.assert_awaited_once_with(session, uid)
