"""Trigger lock TTL·fail-closed 검증."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from app.core.redis import (
    RedisLockUnavailableError,
    acquire_trigger_lock,
)


def test_acquire_trigger_lock_uses_ttl_from_settings():
    """락 획득 시 config.redis_trigger_lock_ttl_seconds를 ex 인자로 사용하는지 검증."""
    from app.core import redis as redis_module

    with patch.object(redis_module.settings, "redis_trigger_lock_ttl_seconds", 3600):
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(return_value=True)
        result = asyncio.run(redis_module.acquire_trigger_lock(mock_client, "engineering"))
        assert result[0] is True
        call_kw = mock_client.set.call_args[1]
        assert call_kw.get("ex") == 3600


def test_acquire_trigger_lock_none_client_returns_true_when_not_required():
    """Redis client None이고 redis_trigger_lock_required False면 (True, None) 반환."""
    from app.core import redis as redis_module

    with patch.object(redis_module.settings, "redis_trigger_lock_required", False):
        result = asyncio.run(acquire_trigger_lock(None, "engineering"))
        assert result == (True, None)


def test_acquire_trigger_lock_none_client_raises_when_required():
    """Redis client None이고 redis_trigger_lock_required True면 RedisLockUnavailableError."""
    from app.core import redis as redis_module

    with patch.object(redis_module.settings, "redis_trigger_lock_required", True):
        with pytest.raises(RedisLockUnavailableError):
            asyncio.run(acquire_trigger_lock(None, "engineering"))
