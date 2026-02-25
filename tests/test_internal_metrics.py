"""GET /internal/metrics Prometheus 노출 및 METRICS_ALLOWED_IPS 검증."""

import pytest


def test_get_metrics_returns_prometheus_text_when_allowed(client, monkeypatch):
    """METRICS_ALLOWED_IPS 미설정 시 200, text/plain, 한 줄 이상 반환."""
    monkeypatch.setattr("app.api.internal.settings.metrics_allowed_ips", "")
    response = client.get("/internal/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    body = response.text
    assert body.endswith("\n")
    lines = [l for l in body.strip().split("\n") if l.strip()]
    assert isinstance(lines, list)


def test_get_metrics_returns_403_when_ip_not_allowed(client, monkeypatch):
    """METRICS_ALLOWED_IPS 설정 시 해당 IP만 허용, 그 외 403."""
    monkeypatch.setattr("app.api.internal.settings.metrics_allowed_ips", "10.0.0.1,10.0.0.2")
    response = client.get("/internal/metrics")
    assert response.status_code == 403
    assert "not allowed" in (response.json().get("detail") or "").lower()
