"""Internal AI admin route guard tests."""

from unittest.mock import AsyncMock, patch

from app.services.ai_admin_service import AdminAiTestResult, AdminCostEstimate, AdminTokenUsage


def test_ai_admin_page_hidden_in_production(client, monkeypatch):
    monkeypatch.setattr("app.api.internal.settings.environment", "production")
    response = client.get("/internal/admin/ai-test")
    assert response.status_code == 404


def test_ai_admin_page_requires_local_client_ip(client, monkeypatch):
    monkeypatch.setattr("app.api.internal.settings.environment", "development")
    with patch("app.api.internal.get_client_ip", return_value="203.0.113.10"):
        response = client.get("/internal/admin/ai-test")
    assert response.status_code == 403


def test_ai_admin_page_allows_localhost(client, monkeypatch):
    monkeypatch.setattr("app.api.internal.settings.environment", "development")

    service = AsyncMock()
    service.list_notice_options.return_value = []
    service.usage_dashboard.return_value = type(
        "Dashboard",
        (),
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "period_days": 30,
            "max_rows": 5000,
            "scanned_rows": 0,
            "source_definition": "test",
            "overall": type(
                "Summary",
                (),
                {
                    "label": "overall",
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0,
                    "average_total_tokens": 0.0,
                    "estimated_cost_usd": None,
                    "valid_usage_count": 0,
                    "missing_usage_count": 0,
                    "invalid_usage_count": 0,
                    "unavailable_usage_count": 0,
                },
            )(),
            "last_24h": type(
                "Summary",
                (),
                {
                    "label": "last_24h",
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0,
                    "average_total_tokens": 0.0,
                    "estimated_cost_usd": None,
                    "valid_usage_count": 0,
                    "missing_usage_count": 0,
                    "invalid_usage_count": 0,
                    "unavailable_usage_count": 0,
                },
            )(),
            "last_7d": type(
                "Summary",
                (),
                {
                    "label": "last_7d",
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0,
                    "average_total_tokens": 0.0,
                    "estimated_cost_usd": None,
                    "valid_usage_count": 0,
                    "missing_usage_count": 0,
                    "invalid_usage_count": 0,
                    "unavailable_usage_count": 0,
                },
            )(),
            "buckets": {},
            "by_model": [],
            "by_college": [],
            "top_notices": [],
        },
    )()

    from app.core.deps import get_ai_admin_service
    from app.main import app

    app.dependency_overrides[get_ai_admin_service] = lambda: service
    try:
        with patch("app.api.internal.get_client_ip", return_value="127.0.0.1"):
            response = client.get("/internal/admin/ai-test")
    finally:
        app.dependency_overrides.pop(get_ai_admin_service, None)
    assert response.status_code == 200
    assert "AI 관리자" in response.text


def test_ai_admin_dry_run_renders_cost_console_quality_labels(client, monkeypatch):
    monkeypatch.setattr("app.api.internal.settings.environment", "development")

    service = AsyncMock()
    service.list_notice_options.return_value = []
    service.usage_dashboard.return_value = type(
        "Dashboard",
        (),
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "period_days": 30,
            "max_rows": 5000,
            "scanned_rows": 1,
            "source_definition": "test",
            "overall": type(
                "Summary",
                (),
                {
                    "label": "overall",
                    "total_tokens": 4287,
                    "prompt_tokens": 3589,
                    "completion_tokens": 204,
                    "call_count": 1,
                    "average_total_tokens": 4287.0,
                    "estimated_cost_usd": 0.0015867,
                    "valid_usage_count": 1,
                    "missing_usage_count": 0,
                    "invalid_usage_count": 0,
                    "unavailable_usage_count": 0,
                },
            )(),
            "last_24h": type(
                "Summary",
                (),
                {
                    "label": "last_24h",
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0,
                    "average_total_tokens": 0.0,
                    "estimated_cost_usd": None,
                    "valid_usage_count": 0,
                    "missing_usage_count": 0,
                    "invalid_usage_count": 0,
                    "unavailable_usage_count": 0,
                },
            )(),
            "last_7d": type(
                "Summary",
                (),
                {
                    "label": "last_7d",
                    "total_tokens": 4287,
                    "prompt_tokens": 3589,
                    "completion_tokens": 204,
                    "call_count": 1,
                    "average_total_tokens": 4287.0,
                    "estimated_cost_usd": 0.0015867,
                    "valid_usage_count": 1,
                    "missing_usage_count": 0,
                    "invalid_usage_count": 0,
                    "unavailable_usage_count": 0,
                },
            )(),
            "buckets": {"3k-10k": 1},
            "by_model": [],
            "by_college": [],
            "top_notices": [],
        },
    )()
    service.run_dry_run.return_value = AdminAiTestResult(
        notice_id="a2ce0183-2242-4bb1-97ca-8ee8c4f94cfd",
        title="test",
        college_name="Engineering",
        college_code="engineering",
        mode="dry_run",
        status="ok",
        html_source="title_fallback",
        remote_fetch_disabled=False,
        image_count_requested=0,
        usage=AdminTokenUsage(prompt_tokens=3589, completion_tokens=204, total_tokens=4287),
        cost=AdminCostEstimate(
            estimated=True,
            currency="USD",
            input_usd_per_1m=0.3,
            output_usd_per_1m=2.5,
            prompt_usd=0.0010767,
            completion_usd=0.00051,
            total_usd=0.0015867,
        ),
        meta={"model": "gemini-2.5-flash", "elapsed_ms": 100, "html_raw_len": 47},
        summary={},
        result={},
        envelope={},
        source_quality="warning",
        usage_quality="valid",
        cost_quality="estimated",
        token_band="3k-10k",
        admin_advice="저장된 본문이 없어 제목만 측정했습니다.",
    )

    from app.core.deps import get_ai_admin_service
    from app.main import app

    app.dependency_overrides[get_ai_admin_service] = lambda: service
    try:
        with patch("app.api.internal.get_client_ip", return_value="127.0.0.1"):
            response = client.post(
                "/internal/admin/ai-test/run",
                data={"notice_id": "a2ce0183-2242-4bb1-97ca-8ee8c4f94cfd"},
            )
    finally:
        app.dependency_overrides.pop(get_ai_admin_service, None)
    assert response.status_code == 200
    assert "Source Quality" in response.text
    assert "Usage Quality" in response.text
    assert "Prompt Tokens" in response.text
    assert '<details class="apply-panel">' in response.text
