"""process_notice_ai_task: manual/fallback/provider-error/정상 경로별 DB 상태 일관성 검증."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import RequestException

from app.core.config import settings
from app.domain.contracts.ai_extraction import NoticeAIExtraction, NoticeCategory
from app.services.tasks import process_notice_ai_task


def test_process_notice_ai_task_manual_edited_calls_update_with_existing_json_only() -> None:
    """manual-edited notice: AI 호출 없이 기존 ai_extracted_json만으로 update_ai_result_sync 호출."""
    notice_id = str(uuid.uuid4())
    existing_json = {"category": "scholarship", "metadata": {}}
    mock_notice = MagicMock()
    mock_notice.is_manual_edited = True
    mock_notice.ai_extracted_json = existing_json

    with (
        patch.object(settings, "ai_pipeline_enabled", True),
        patch("app.services.tasks.get_sync_session") as mock_session_ctx,
        patch("app.services.tasks.get_notice_for_ai_sync", return_value=mock_notice) as mock_get,
        patch("app.services.tasks.update_ai_result_sync") as mock_update,
        patch("app.services.tasks.extract_notice_info") as mock_extract,
    ):
        session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = session
        process_notice_ai_task.apply(args=(notice_id,), throw=True)

    mock_get.assert_called_once()
    mock_extract.assert_not_called()
    mock_update.assert_called_once()
    call_kw = mock_update.call_args
    assert call_kw[0][1] == uuid.UUID(notice_id)
    assert call_kw[0][2] == existing_json
    assert call_kw[1].get("dates") is None
    assert call_kw[1].get("eligibility") is None


def test_process_notice_ai_task_normal_notice_calls_update_with_projected_fields() -> None:
    """정상 notice: extract_notice_info ok → update_ai_result_sync에 ai_extracted_json·dates·eligibility 등 전달."""
    notice_id = str(uuid.uuid4())
    mock_notice = MagicMock()
    mock_notice.is_manual_edited = False
    mock_notice.title = "공지"
    mock_notice.notice_content = None

    stub = NoticeAIExtraction(category=NoticeCategory.SCHOLARSHIP, target_departments=[])
    envelope = MagicMock()
    envelope.result = stub
    envelope.meta = {"provider": "google/gemini-1.5-flash", "model": "gemini-1.5-flash", "fallback_reason": None}
    envelope.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    with (
        patch.object(settings, "ai_pipeline_enabled", True),
        patch("app.services.tasks.get_sync_session") as mock_session_ctx,
        patch("app.services.tasks.get_notice_for_ai_sync", return_value=mock_notice),
        patch("app.services.tasks.update_ai_result_sync") as mock_update,
        patch("app.services.tasks.extract_notice_info", return_value=envelope),
        patch("app.services.tasks._get_notice_html_for_ai", return_value="<p>body</p>"),
        patch("app.services.tasks._get_notice_image_urls_for_ai", return_value=[]),
    ):
        session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = session
        process_notice_ai_task.apply(args=(notice_id,), throw=True)

    mock_update.assert_called_once()
    call = mock_update.call_args
    ai_json = call[0][2]
    assert "category" in ai_json
    assert call[1]["dates"] is not None
    assert call[1]["eligibility"] is not None
    assert call[1].get("category") == "scholarship"


def test_process_notice_ai_task_fallback_notice_updates_with_fallback_envelope_meta() -> None:
    """fallback notice: envelope.status=fallback여도 update_ai_result_sync에 _envelope_meta 포함된 JSON 저장."""
    notice_id = str(uuid.uuid4())
    mock_notice = MagicMock()
    mock_notice.is_manual_edited = False
    mock_notice.notice_content = None

    fallback_result = NoticeAIExtraction(target_departments=[])
    envelope = MagicMock()
    envelope.result = fallback_result
    envelope.meta = {
        "provider": "google/gemini-1.5-flash",
        "model": "gemini-1.5-flash",
        "fallback_reason": "validation_error",
        "html_raw_len": 100,
        "html_clean_len": 80,
        "image_count": 0,
        "elapsed_ms": 50,
    }
    envelope.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    with (
        patch.object(settings, "ai_pipeline_enabled", True),
        patch("app.services.tasks.get_sync_session") as mock_session_ctx,
        patch("app.services.tasks.get_notice_for_ai_sync", return_value=mock_notice),
        patch("app.services.tasks.update_ai_result_sync") as mock_update,
        patch("app.services.tasks.extract_notice_info", return_value=envelope),
        patch("app.services.tasks._get_notice_html_for_ai", return_value="<p>body</p>"),
        patch("app.services.tasks._get_notice_image_urls_for_ai", return_value=[]),
    ):
        session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = session
        process_notice_ai_task.apply(args=(notice_id,), throw=True)

    mock_update.assert_called_once()
    ai_json = mock_update.call_args[0][2]
    assert ai_json.get("metadata", {}).get("_envelope_meta", {}).get("fallback_reason") == "validation_error"


def test_process_notice_ai_task_provider_error_does_not_call_update_and_raises() -> None:
    """provider error: extract_notice_info가 예외를 던지면 update_ai_result_sync 미호출, 예외 전파."""
    notice_id = str(uuid.uuid4())
    mock_notice = MagicMock()
    mock_notice.is_manual_edited = False
    mock_notice.notice_content = None

    with (
        patch.object(settings, "ai_pipeline_enabled", True),
        patch("app.services.tasks.get_sync_session") as mock_session_ctx,
        patch("app.services.tasks.get_notice_for_ai_sync", return_value=mock_notice),
        patch("app.services.tasks.update_ai_result_sync") as mock_update,
        patch("app.services.tasks.extract_notice_info", side_effect=RequestException("network")),
        patch("app.services.tasks._get_notice_html_for_ai", return_value="<p>body</p>"),
        patch("app.services.tasks._get_notice_image_urls_for_ai", return_value=[]),
        patch.object(process_notice_ai_task, "retry") as mock_retry,
    ):
        def _raise_original(exc=None, *args, **kwargs):
            # Celery autoretry는 기본적으로 Retry 예외를 던지지만,
            # 이 테스트에서는 원래 provider 예외(RequestException)를 그대로 전파하도록 강제한다.
            raise exc or RequestException("network")

        mock_retry.side_effect = lambda *args, **kwargs: _raise_original(kwargs.get("exc"))
        session = MagicMock()
        mock_session_ctx.return_value.__enter__.return_value = session
        with pytest.raises(RequestException):
            process_notice_ai_task.apply(args=(notice_id,), throw=True)

    mock_update.assert_not_called()
