"""Health 엔드포인트 테스트. Liveness(/live) vs Readiness(/ready) 분리."""

import pytest


@pytest.mark.asyncio
async def test_live_returns_200_always(async_client):
    """GET /live → 200. DB/Redis 미체크."""
    response = await async_client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_returns_200_or_503(async_client):
    """GET /ready → DB·Redis(blocklist·trigger_lock) 준비 시 200, 아니면 503."""
    response = await async_client.get("/ready")
    data = response.json()
    assert "status" in data
    assert "db" in data
    assert "redis_blocklist" in data
    assert "redis_trigger_lock" in data
    if response.status_code == 200:
        assert data["status"] == "ok"
    else:
        assert response.status_code == 503
        assert data["status"] == "not_ready"


@pytest.mark.asyncio
async def test_ready_includes_last_crawl_success_when_snapshot_available(async_client, monkeypatch):
    """Redis 스냅샷이 있으면 last_crawl_success 필드를 노출(ready 판정과 독립)."""
    from app.api import health as health_module

    async def _mock_db_ok(_request):
        return "ok"

    async def _mock_blocklist_ok(_request):
        return "ok"

    async def _mock_trigger_lock_ok(_request):
        return "ok"

    async def _mock_last(_request):
        return {"engineering": "2026-03-27T12:00:00+00:00"}

    monkeypatch.setattr(health_module, "_check_db", _mock_db_ok)
    monkeypatch.setattr(health_module, "_check_redis_blocklist", _mock_blocklist_ok)
    monkeypatch.setattr(health_module, "_check_redis_trigger_lock", _mock_trigger_lock_ok)
    monkeypatch.setattr(health_module, "_last_crawl_success_snapshot", _mock_last)

    response = await async_client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["last_crawl_success"] == {"engineering": "2026-03-27T12:00:00+00:00"}


@pytest.mark.parametrize("redis_blocklist_fail_closed", [False, True])
@pytest.mark.asyncio
async def test_ready_blocklist_error_returns_503(async_client, monkeypatch, redis_blocklist_fail_closed):
    """Readiness는 의존성 상태 그대로 노출. blocklist Redis 장애 시 fail_closed와 무관하게 항상 503."""
    from app.api import health as health_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "redis_blocklist_fail_closed", redis_blocklist_fail_closed)

    async def _mock_db_ok(_request):
        return "ok"

    async def _mock_blocklist_error(_request):
        return "error"

    async def _mock_trigger_lock_ok(_request):
        return "ok"

    monkeypatch.setattr(health_module, "_check_db", _mock_db_ok)
    monkeypatch.setattr(health_module, "_check_redis_blocklist", _mock_blocklist_error)
    monkeypatch.setattr(health_module, "_check_redis_trigger_lock", _mock_trigger_lock_ok)

    response = await async_client.get("/ready")
    data = response.json()
    assert data["redis_blocklist"] == "error"
    assert response.status_code == 503
    assert data["status"] == "not_ready"


@pytest.mark.asyncio
async def test_health_returns_200(async_client):
    """GET /health → 200 + status ok (플랫폼 헬스체크용, DB/Redis 미체크)."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "ok"}


@pytest.mark.asyncio
async def test_worker_health_returns_200_when_worker_alive(async_client, monkeypatch):
    from app.api import health as health_module

    async def _mock_ok():
        return ("ok", ["celery@dicee-worker-1"], None)

    monkeypatch.setattr(health_module, "_check_celery_workers", _mock_ok)

    response = await async_client.get("/health/worker")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["celery"] == "ok"
    assert data["active_worker_count"] == 1
    assert data["workers"] == ["celery@dicee-worker-1"]


@pytest.mark.asyncio
async def test_worker_health_returns_503_when_worker_unavailable(async_client, monkeypatch):
    from app.api import health as health_module

    async def _mock_unavailable():
        return ("error", [], "broker_not_configured")

    monkeypatch.setattr(health_module, "_check_celery_workers", _mock_unavailable)

    response = await async_client.get("/health/worker")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["celery"] == "error"
    assert data["reason"] == "broker_not_configured"
