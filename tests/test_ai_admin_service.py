"""Local AI admin safety tests."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app.domain.contracts.ai_extraction import NoticeAIExtraction
from app.services.ai.exceptions import AIProviderRetryableError
from app.services.ai.types import TokenUsage
from app.services.ai_admin_service import (
    AdminTokenUsage,
    AiAdminDependencyUnavailableError,
    AiAdminService,
    _read_local_notice_html,
    _source_quality,
    estimate_cost,
    result_to_payload,
)
from app.services.ai_pipeline import ExtractionEnvelope, ExtractionRunMeta


def test_ai_admin_remote_html_fetch_is_disabled() -> None:
    html = _read_local_notice_html("https://example.com/notice.html", "테스트 공지")
    assert html.source == "remote_fetch_disabled"
    assert html.remote_fetch_disabled is True
    assert html.html == "<title>테스트 공지</title>"


def test_ai_admin_cost_uses_default_gemini_price_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.ai_admin_service.settings.ai_admin_model_costs_usd_per_million",
        "",
    )
    cost = estimate_cost(
        "gemini-2.5-flash",
        AdminTokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000, total_tokens=1_500_000),
    )
    assert cost.estimated is True
    assert cost.total_usd == pytest.approx(1.55)


def test_ai_admin_cost_unknown_for_unpriced_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.ai_admin_service.settings.ai_admin_model_costs_usd_per_million",
        "",
    )
    cost = estimate_cost("custom-model", AdminTokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500))
    assert cost.total_usd is None
    assert cost.reason == "unknown_model_cost"


def test_ai_admin_cost_unknown_when_llm_usage_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ai_admin_service import _build_test_result

    monkeypatch.setattr(
        "app.services.ai_admin_service.settings.ai_admin_model_costs_usd_per_million",
        "",
    )
    notice = SimpleNamespace(
        id=uuid.uuid4(),
        title="usage missing",
        images=[],
        college=SimpleNamespace(name="Engineering", external_id="engineering"),
    )
    html_input = SimpleNamespace(source="title_fallback", remote_fetch_disabled=False)
    envelope = ExtractionEnvelope(
        status="ok",
        result=NoticeAIExtraction(target_departments=[]),
        usage=TokenUsage(),
        meta=ExtractionRunMeta(model="gemini-2.5-flash", provider="google/gemini-2.5-flash", llm_call_count=1),
    )

    result = _build_test_result(
        notice=notice,
        mode="dry_run",
        html_input=html_input,
        image_urls=[],
        envelope=envelope,
    )

    assert result.cost.total_usd is None
    assert result.cost.reason == "usage_unavailable"
    assert result.usage_quality == "unavailable"
    assert result.cost_quality == "usage_unavailable"
    assert result.source_quality == "warning"
    assert result.token_band == "0-1k"


def test_ai_admin_source_quality_classification() -> None:
    assert _source_quality("local_content_url") == "ok"
    assert _source_quality("title_fallback") == "warning"
    assert _source_quality("remote_fetch_disabled") == "warning"
    assert _source_quality("path_blocked") == "blocked"


def test_ai_admin_local_content_url_source_is_ok(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = tmp_path / "notice.html"
    content.write_text("<main>body</main>", encoding="utf-8")
    monkeypatch.setattr("app.services.ai_admin_service.settings.content_storage_local_path", str(tmp_path))

    html = _read_local_notice_html("notice.html", "title")

    assert html.source == "local_content_url"
    assert _source_quality(html.source) == "ok"
    assert html.html == "<main>body</main>"


def test_ai_admin_cost_uses_configured_price_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.ai_admin_service.settings.ai_admin_model_costs_usd_per_million",
        "gemini-2.0-flash:0.10:0.40",
    )
    cost = estimate_cost(
        "gemini-2.0-flash",
        AdminTokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000, total_tokens=1_500_000),
    )
    assert cost.total_usd == pytest.approx(0.30)
    assert cost.estimated is True


@pytest.mark.asyncio
async def test_ai_admin_dry_run_reads_notice_without_status_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    notice_id = uuid.uuid4()
    notice = SimpleNamespace(
        id=notice_id,
        title="테스트 공지",
        images=[],
        notice_content=SimpleNamespace(content_url="https://example.com/blocked"),
        college=SimpleNamespace(name="공과대학", external_id="engineering"),
    )
    envelope = ExtractionEnvelope(
        status="ok",
        result=NoticeAIExtraction(target_departments=[]),
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        meta=ExtractionRunMeta(model="gemini-2.0-flash", provider="google/gemini-2.0-flash", elapsed_ms=123),
    )
    session = AsyncMock()
    monkeypatch.setattr("app.services.ai_admin_service.get_notice_for_ai_admin", AsyncMock(return_value=notice))
    with (
        patch("app.services.ai_admin_service.extract_notice_info", return_value=envelope) as mock_extract,
        patch("app.repositories.notice_repository.get_notice_for_ai_sync") as forbidden_claim,
    ):
        result = await AiAdminService().run_dry_run(session, notice_id=str(notice_id), include_vision=True)
    forbidden_claim.assert_not_called()
    assert result.mode == "dry_run"
    assert result.updated_rows == 0
    assert result.html_source == "remote_fetch_disabled"
    assert result.source_quality == "warning"
    assert "원격 본문 fetch" in result.admin_advice
    assert result.usage.total_tokens == 15
    assert result.usage_quality == "valid"
    assert result.cost_quality == "estimated"
    assert result.token_band == "0-1k"
    assert mock_extract.call_args.args[0] == "<title>테스트 공지</title>"


@pytest.mark.asyncio
async def test_ai_admin_dry_run_maps_provider_quota_error(monkeypatch: pytest.MonkeyPatch) -> None:
    notice_id = uuid.uuid4()
    notice = SimpleNamespace(
        id=notice_id,
        title="테스트 공지",
        images=[],
        notice_content=SimpleNamespace(content_url=""),
        college=SimpleNamespace(name="공과대학", external_id="engineering"),
    )
    monkeypatch.setattr("app.services.ai_admin_service.get_notice_for_ai_admin", AsyncMock(return_value=notice))
    with patch("app.services.ai_admin_service.extract_notice_info", side_effect=AIProviderRetryableError("quota")):
        with pytest.raises(AiAdminDependencyUnavailableError, match="quota"):
            await AiAdminService().run_dry_run(AsyncMock(), notice_id=str(notice_id), include_vision=False)


@pytest.mark.asyncio
async def test_ai_admin_apply_requires_redis() -> None:
    with pytest.raises(AiAdminDependencyUnavailableError):
        await AiAdminService().prepare_apply_claim(
            None,
            notice_id=str(uuid.uuid4()),
            idempotency_key="key-1",
        )


@pytest.mark.asyncio
async def test_ai_admin_apply_one_notice_and_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    notice_id = uuid.uuid4()
    notice = SimpleNamespace(
        id=notice_id,
        title="테스트 공지",
        images=[],
        notice_content=SimpleNamespace(content_url=""),
        college=SimpleNamespace(name="공과대학", external_id="engineering"),
    )
    envelope = ExtractionEnvelope(
        status="ok",
        result=NoticeAIExtraction(target_departments=[]),
        usage=TokenUsage(prompt_tokens=20, completion_tokens=7, total_tokens=27),
        meta=ExtractionRunMeta(model="gemini-2.0-flash", provider="google/gemini-2.0-flash", elapsed_ms=99),
    )
    update = AsyncMock(return_value=1)
    replace_schedules = AsyncMock()
    monkeypatch.setattr("app.services.ai_admin_service.get_notice_for_ai_admin", AsyncMock(return_value=notice))
    monkeypatch.setattr("app.services.ai_admin_service.update_ai_result_admin", update)
    monkeypatch.setattr("app.services.ai_admin_service.replace_notice_schedules", replace_schedules)
    with patch("app.services.ai_admin_service.extract_notice_info", return_value=envelope):
        claim = SimpleNamespace(notice_id=notice_id, idempotency_key="key-1", scope="scope", lock_token="token")
        result = await AiAdminService().run_apply(
            AsyncMock(),
            claim=claim,
            include_vision=False,
            confirmation=str(notice_id),
        )
    assert result.mode == "apply"
    assert result.updated_rows == 1
    assert update.call_args.args[1] == notice_id
    saved_json = update.call_args.args[2]
    meta = saved_json["metadata"]["_envelope_meta"]
    assert meta["admin_run"] is True
    assert meta["admin_mode"] == "apply"
    replace_schedules.assert_awaited_once()
    assert result_to_payload(result)["notice_id"] == str(notice_id)


@pytest.mark.asyncio
async def test_ai_admin_usage_dashboard_separates_missing_and_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            title="valid",
            college_name="공과대학",
            college_code="engineering",
            updated_at=now,
            published_at=now,
            ai_extracted_json={
                "metadata": {
                    "_envelope_meta": {
                        "model": "gemini-2.0-flash",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    }
                }
            },
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            title="missing",
            college_name="공과대학",
            college_code="engineering",
            updated_at=now,
            published_at=now,
            ai_extracted_json={"metadata": {}},
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            title="invalid",
            college_name="문과대학",
            college_code="liberal",
            updated_at=now,
            published_at=now,
            ai_extracted_json={"metadata": {"_envelope_meta": {"model": "m", "usage": {"total_tokens": "bad"}}}},
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            title="unavailable",
            college_name="Engineering",
            college_code="engineering",
            updated_at=now,
            published_at=now,
            ai_extracted_json={
                "metadata": {
                    "_envelope_meta": {
                        "model": "gemini-2.5-flash",
                        "llm_call_count": 1,
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    }
                }
            },
        ),
    ]
    monkeypatch.setattr(
        "app.services.ai_admin_service.list_ai_usage_source_rows_for_admin",
        AsyncMock(return_value=rows),
    )
    dashboard = await AiAdminService().usage_dashboard(AsyncMock(), period_days=30, limit=100)
    assert dashboard.overall.total_tokens == 15
    assert dashboard.overall.call_count == 1
    assert dashboard.overall.valid_usage_count == 1
    assert dashboard.overall.missing_usage_count == 1
    assert dashboard.overall.invalid_usage_count == 1
    assert dashboard.overall.unavailable_usage_count == 1
    assert dashboard.buckets["0-1k"] == 1
