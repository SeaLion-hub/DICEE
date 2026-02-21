"""Auth Service 단위 테스트. DB/Google 호출 없이 검증."""

from unittest.mock import patch

import pytest
from app.services.auth_service import AuthError, create_jwt_pair, decode_google_id_token


def test_create_jwt_pair_returns_two_tokens() -> None:
    """create_jwt_pair: JWT_SECRET 설정 시 access, refresh 두 토큰 반환."""
    access, refresh = create_jwt_pair(user_id=1)
    assert isinstance(access, str)
    assert isinstance(refresh, str)
    assert len(access) > 0
    assert len(refresh) > 0
    assert access != refresh


def test_create_jwt_pair_raises_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_jwt_pair: JWT_SECRET 없으면 AuthError."""
    monkeypatch.setattr("app.services.auth_service.settings.jwt_secret", "")
    with pytest.raises(AuthError):
        create_jwt_pair(user_id=1)


@patch("app.services.auth_service.google_id_token.verify_oauth2_token")
def test_decode_google_id_token_valid(
    mock_verify: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """decode_google_id_token: verify_oauth2_token mock 시 claims 반환."""
    monkeypatch.setattr(
        "app.services.auth_service.settings.google_client_id", "test-client-id"
    )
    mock_verify.return_value = {"sub": "123", "email": "a@b.com", "name": "Test"}
    result = decode_google_id_token("fake-id-token")
    assert result["sub"] == "123"
    assert result["email"] == "a@b.com"
