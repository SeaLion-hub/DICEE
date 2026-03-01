"""Read cache Soft TTL + Mutex (cache stampede 방지) 검증."""

import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from app.core.redis import (
    CACHE_LOCK_KEY_PREFIX,
    get_cache_with_soft_ttl,
    release_cache_lock,
)


@pytest.mark.asyncio
async def test_get_cache_with_soft_ttl_returns_lock_token_when_acquired() -> None:
    """Hard miss 시 락 획득하면 (None, True, token) 반환. token은 UUID 형식."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)

    data, should_refresh, token = await get_cache_with_soft_ttl(client, "k", lock_ttl_seconds=10)

    assert data is None
    assert should_refresh is True
    assert token is not None
    assert len(token) == 36  # UUID string
    client.set.assert_called_once()
    call_args = client.set.call_args
    assert call_args[0][0] == f"{CACHE_LOCK_KEY_PREFIX}k"
    assert call_args[1]["nx"] is True
    assert call_args[1]["ex"] == 10


@pytest.mark.asyncio
async def test_get_cache_with_soft_ttl_fresh_returns_no_token() -> None:
    """Soft TTL 이내 캐시는 (data, False, None) 반환."""
    payload = {"data": {"x": 1}, "soft_ttl": time.time() + 60}
    client = AsyncMock()
    client.get = AsyncMock(return_value=json.dumps(payload))

    data, should_refresh, token = await get_cache_with_soft_ttl(client, "k", lock_ttl_seconds=10)

    assert data == {"x": 1}
    assert should_refresh is False
    assert token is None
    client.set.assert_not_called()


@pytest.mark.asyncio
async def test_get_cache_with_soft_ttl_stale_lock_acquired_returns_token() -> None:
    """Stale 캐시 + 락 획득 시 (data, True, token) 반환."""
    payload = {"data": {"a": 1}, "soft_ttl": time.time() - 1}
    client = AsyncMock()
    client.get = AsyncMock(return_value=json.dumps(payload))
    client.set = AsyncMock(return_value=True)

    data, should_refresh, token = await get_cache_with_soft_ttl(client, "key", lock_ttl_seconds=5)

    assert data == {"a": 1}
    assert should_refresh is True
    assert token is not None


@pytest.mark.asyncio
async def test_get_cache_with_soft_ttl_stale_lock_not_acquired_returns_stale_no_token() -> None:
    """Stale + 락 미획득 시 (data, False, None) — stale 즉시 반환."""
    payload = {"data": {"b": 2}, "soft_ttl": time.time() - 1}
    client = AsyncMock()
    client.get = AsyncMock(return_value=json.dumps(payload))
    client.set = AsyncMock(return_value=False)  # NX 실패

    data, should_refresh, token = await get_cache_with_soft_ttl(client, "k", lock_ttl_seconds=10)

    assert data == {"b": 2}
    assert should_refresh is False
    assert token is None


@pytest.mark.asyncio
async def test_release_cache_lock_compare_and_del_eval() -> None:
    """release_cache_lock은 token으로 Lua compare-and-del 호출."""
    client = AsyncMock()
    client.eval = AsyncMock(return_value=1)

    await release_cache_lock(client, "mykey", "my-token-123")

    client.eval.assert_called_once()
    args = client.eval.call_args[0]
    assert args[1] == 1
    assert args[2] == f"{CACHE_LOCK_KEY_PREFIX}mykey"
    assert args[3] == "my-token-123"


@pytest.mark.asyncio
async def test_release_cache_lock_no_op_when_token_empty() -> None:
    """token이 비어 있으면 eval 호출하지 않음."""
    client = AsyncMock()

    await release_cache_lock(client, "k", "")
    client.eval.assert_not_called()


@pytest.mark.asyncio
async def test_read_cache_wait_for_cached_then_refresh() -> None:
    """wait_for_cached 후 get_cached_with_soft_ttl 재호출 시 캐시 hit 가능."""
    from app.core.read_cache import get_cached_with_soft_ttl, wait_for_cached

    with patch("app.core.read_cache.settings") as mock_settings:
        mock_settings.read_cache_lock_ttl_seconds = 10
        mock_settings.read_cache_wait_for_fresh_ms = 10
        client = AsyncMock()
        # 첫 호출: miss + no lock. 두 번째 호출(재조회): fresh
        payload1 = None
        payload2 = {"data": {"runs": [], "limit": 50}, "soft_ttl": time.time() + 60}
        client.get = AsyncMock(side_effect=[payload1, json.dumps(payload2)])
        client.set = AsyncMock(return_value=False)

        # 첫 get: miss, no lock
        data1, should_refresh1, token1 = await get_cached_with_soft_ttl(client, "crawl_stats", "50")
        assert data1 is None
        assert token1 is None

        # wait 후 재조회: 다른 코루틴이 채워둔 상태 가정 — 한 번 더 get
        client.get.return_value = json.dumps(payload2)
        data2, _, _ = await wait_for_cached(client, 5, "crawl_stats", "50")
        assert data2 == {"runs": [], "limit": 50}


@pytest.mark.asyncio
async def test_crawl_stats_fresh_hit_does_not_call_db(client) -> None:
    """Fresh hit 시 캐시에서 즉시 반환 (DB 미호출)."""
    from app.api import internal as internal_module
    from app.core.database import get_read_only_db
    from app.main import app

    def _noop_authorize(*args, **kwargs):
        pass

    async def _fake_get_read_only_db():
        class _DummySession:
            pass

        yield _DummySession()

    app.dependency_overrides[get_read_only_db] = _fake_get_read_only_db
    try:
        with patch.object(internal_module, "_authorize_internal_trigger", _noop_authorize):
            with patch.object(
                internal_module,
                "get_cached_with_soft_ttl",
                AsyncMock(return_value=({"runs": [], "limit": 50}, False, None)),
            ):
                resp = client.get(
                    "/internal/crawl-stats",
                    headers={"X-Crawl-Trigger-Secret": "test-secret"},
                )
                assert resp.status_code == 200
                assert resp.json()["limit"] == 50
    finally:
        app.dependency_overrides.pop(get_read_only_db, None)


@pytest.mark.asyncio
async def test_crawl_stats_degraded_no_cache_returns_503(client) -> None:
    """DEGRADED 모드에서 캐시 없음 + wait 후에도 없으면 503."""
    from app.api import internal as internal_module
    from app.core.database import get_read_only_db
    from app.main import app

    def _noop_authorize(*args, **kwargs):
        pass

    async def _fake_get_read_only_db():
        class _DummySession:
            pass

        yield _DummySession()

    app.dependency_overrides[get_read_only_db] = _fake_get_read_only_db
    client.app.state.operational_mode = "DEGRADED"
    try:
        with patch.object(internal_module, "_authorize_internal_trigger", _noop_authorize):
            with patch.object(
                internal_module,
                "get_cached_with_soft_ttl",
                AsyncMock(return_value=(None, False, None)),
            ):
                with patch.object(
                    internal_module,
                    "wait_for_cached",
                    AsyncMock(return_value=(None, False, None)),
                ):
                    resp = client.get(
                        "/internal/crawl-stats",
                        headers={"X-Crawl-Trigger-Secret": "test-secret"},
                    )
                    assert resp.status_code == 503
    finally:
        app.dependency_overrides.pop(get_read_only_db, None)
