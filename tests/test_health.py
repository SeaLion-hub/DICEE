"""Health 엔드포인트 테스트. Liveness(/live) vs Readiness(/ready) 분리."""

import pytest


def test_live_returns_200_always(client):
    """GET /live → 200. DB/Redis 미체크."""
    response = client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_200_or_503(client):
    """GET /ready → DB·Redis(blocklist·trigger_lock) 준비 시 200, 아니면 503."""
    response = client.get("/ready")
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


@pytest.mark.parametrize("redis_blocklist_fail_closed,expect_ready_ok", [(False, True), (True, False)])
def test_ready_fail_open_blocklist(client, monkeypatch, redis_blocklist_fail_closed, expect_ready_ok):
    """Fail-Open이면 blocklist Redis 장애만으로는 /ready 200. Fail-Closed면 503."""
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

    response = client.get("/ready")
    data = response.json()
    assert data["redis_blocklist"] == "error"
    if expect_ready_ok:
        assert response.status_code == 200
        assert data["status"] == "ok"
    else:
        assert response.status_code == 503
        assert data["status"] == "not_ready"


def test_health_returns_200(client):
    """GET /health → 200 + status ok (플랫폼 헬스체크용, DB/Redis 미체크)."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "ok"}
