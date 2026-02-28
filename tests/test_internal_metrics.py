"""GET /internal/metrics Prometheus 노출 및 METRICS_ALLOWED_IPS 검증 (fail-closed: 미설정 시 전체 차단)."""


def test_get_metrics_returns_403_when_empty_fail_closed(client, monkeypatch):
    """METRICS_ALLOWED_IPS 미설정(빈 값) 시 모든 IP 차단(fail-closed) → 403."""
    monkeypatch.setattr("app.api.internal.settings.metrics_allowed_ips", "")
    response = client.get("/internal/metrics")
    assert response.status_code == 403
    assert "not allowed" in (response.json().get("detail") or "").lower()


def test_get_metrics_returns_prometheus_text_when_allowed(client, monkeypatch):
    """METRICS_ALLOWED_IPS에 클라이언트 IP가 포함되면 200, text/plain, 한 줄 이상 반환."""
    # TestClient 기본 host는 "testclient"
    monkeypatch.setattr("app.api.internal.settings.metrics_allowed_ips", "testclient,127.0.0.1")
    response = client.get("/internal/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    body = response.text
    assert body.endswith("\n")
    lines = [line for line in body.strip().split("\n") if line.strip()]
    assert isinstance(lines, list)


def test_get_metrics_returns_403_when_ip_not_allowed(client, monkeypatch):
    """METRICS_ALLOWED_IPS 설정 시 해당 IP만 허용, 그 외 403."""
    monkeypatch.setattr("app.api.internal.settings.metrics_allowed_ips", "10.0.0.1,10.0.0.2")
    response = client.get("/internal/metrics")
    assert response.status_code == 403
    assert "not allowed" in (response.json().get("detail") or "").lower()
