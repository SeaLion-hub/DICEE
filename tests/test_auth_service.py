"""Auth Service 단위 테스트. DB/Google 호출 없이 검증."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

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
    """create_jwt_pair: JWT_SECRET 비어 있으면 AuthError."""
    monkeypatch.setattr(
        "app.services.auth_service.settings.jwt_secret",
        SecretStr(""),
    )
    with pytest.raises(AuthError):
        create_jwt_pair(user_id=1)


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
