"""Auth Service 단위 테스트. DB/Google 호출 없이 검증."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.services.auth_service import AuthError, create_jwt_pair, decode_google_id_token
from pydantic import SecretStr


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
    """_allowed_redirect_uris: google_redirect_uris에 값이 있으나 유효한 URI가 없으면 AuthError (P0 fail-closed 회귀 방지)."""
    from app.services.auth_service import AuthError, _allowed_redirect_uris

    monkeypatch.setattr("app.services.auth_service.settings.google_redirect_uris", "http://invalid??,not-a-uri")
    _allowed_redirect_uris.cache_clear()
    try:
        with pytest.raises(AuthError, match="google_redirect_uris.*no valid"):
            _allowed_redirect_uris()
    finally:
        _allowed_redirect_uris.cache_clear()
