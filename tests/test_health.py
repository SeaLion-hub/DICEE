"""Health 엔드포인트 테스트."""


def test_health_returns_200(client):
    """GET /health → 200 + {"status":"ok"}."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
