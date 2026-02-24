"""Health 엔드포인트 테스트. Liveness(/live) vs Readiness(/ready) 분리."""


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


def test_health_returns_200(client):
    """GET /health → 200 + status, db, redis_blocklist, redis_trigger_lock."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] in ("ok", "degraded")
    assert "db" in data
    assert data["db"] in ("ok", "error")
    assert "redis_blocklist" in data
    assert data["redis_blocklist"] in ("ok", "error")
    assert "redis_trigger_lock" in data
    assert data["redis_trigger_lock"] in ("ok", "error")
