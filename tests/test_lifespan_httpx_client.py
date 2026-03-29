"""Shared httpx client: explicit timeout and limits from settings."""

from types import SimpleNamespace

import pytest
from app.core import lifespan as lifespan_mod
from app.core.config.base import Settings
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_build_app_httpx_client_uses_patched_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = SimpleNamespace(
        http_client_connect_timeout_seconds=12.0,
        http_client_read_timeout_seconds=45.0,
        http_client_write_timeout_seconds=46.0,
        http_client_pool_timeout_seconds=8.0,
        http_client_max_connections=50,
        http_client_max_keepalive_connections=10,
    )
    monkeypatch.setattr(lifespan_mod, "settings", fake)
    client = lifespan_mod.build_app_httpx_client()
    try:
        assert client.timeout.connect == 12.0
        assert client.timeout.read == 45.0
        assert client.timeout.write == 46.0
        assert client.timeout.pool == 8.0
    finally:
        await client.aclose()


def test_settings_rejects_keepalive_above_max_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENTRY", "celery")
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            http_client_max_connections=10,
            http_client_max_keepalive_connections=20,
        )
    assert "keepalive" in str(exc_info.value).lower()
