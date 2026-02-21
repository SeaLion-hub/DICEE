"""Health 엔드포인트 테스트."""


def test_health_returns_200(client):
    """GET /health → 200 + status, db, redis 키. (테스트 환경은 DB 미설정이므로 status는 ok 또는 degraded)."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] in ("ok", "degraded")
    assert "db" in data
    assert data["db"] in ("ok", "error")
    assert "redis" in data
    assert data["redis"] in ("ok", "error")
