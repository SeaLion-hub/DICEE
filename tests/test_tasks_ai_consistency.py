"""process_notice_ai_task: manual/fallback/provider-error/정상 경로별 DB 상태 일관성 검증."""

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from app.domain.contracts.ai_extraction import NoticeAIExtraction, NoticeCategory
from app.services.tasks import process_notice_ai_task
from requests.exceptions import RequestException


def _multi_get_sync_session(*sessions: MagicMock):
    """get_sync_session이 호출될 때마다 다음 세션을 yield하는 컨텍스트 매니저를 반환."""

    it = iter(sessions)

    def factory():
        sess = next(it)

        @contextmanager
        def cm():
            yield sess

        return cm()

    return factory


def test_process_notice_ai_task_manual_edited_calls_update_with_existing_json_only() -> None:
    """manual-edited notice: AI 호출 없이 기존 ai_extracted_json만으로 update_ai_result_sync 호출."""
    notice_id = str(uuid.uuid4())
    nid = uuid.UUID(notice_id)
    existing_json = {"category": "scholarship", "metadata": {}}
    mock_notice = MagicMock()
    mock_notice.is_manual_edited = True
    mock_notice.ai_extracted_json = existing_json
    mock_notice.id = nid
    mock_notice.title = "t"
    mock_notice.notice_content = None
    mock_notice.images = None
    mock_notice.college = MagicMock(external_id="c1", name="Col")

    session = MagicMock()
    with (
        patch("app.core.config.settings.ai_pipeline_enabled", True),
        patch("app.services.tasks.get_sync_session", side_effect=_multi_get_sync_session(session)),
        patch("app.services.tasks.get_notice_for_ai_sync", return_value=mock_notice) as mock_get,
        patch("app.services.tasks.update_ai_result_sync", return_value=1) as mock_update,
        patch("app.services.tasks.extract_notice_info") as mock_extract,
    ):
        process_notice_ai_task.apply(args=(notice_id,), throw=True)

    mock_get.assert_called_once()
    mock_extract.assert_not_called()
    mock_update.assert_called_once()
    call_kw = mock_update.call_args
    assert call_kw[0][1] == nid
    assert call_kw[0][2] == existing_json
    assert call_kw[1].get("dates") is None
    assert call_kw[1].get("eligibility") is None


def test_process_notice_ai_task_normal_notice_calls_update_with_projected_fields() -> None:
    """정상 notice: extract_notice_info ok → update_ai_result_sync에 ai_extracted_json·dates·eligibility 등 전달."""
    notice_id = str(uuid.uuid4())
    nid = uuid.UUID(notice_id)
    mock_notice = MagicMock()
    mock_notice.is_manual_edited = False
    mock_notice.title = "공지"
    mock_notice.notice_content = None
    mock_notice.images = None
    mock_notice.id = nid
    mock_college = MagicMock()
    mock_college.name = "단과대"
    mock_college.external_id = "eng"
    mock_notice.college = mock_college

    stub = NoticeAIExtraction(category=NoticeCategory.SCHOLARSHIP, target_departments=[])
    envelope = MagicMock()
    envelope.result = stub
    envelope.meta = {"provider": "google/gemini-1.5-flash", "model": "gemini-1.5-flash", "fallback_reason": None}
    envelope.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    s1, s2 = MagicMock(), MagicMock()
    with (
        patch("app.core.config.settings.ai_pipeline_enabled", True),
        patch("app.services.tasks.get_sync_session", side_effect=_multi_get_sync_session(s1, s2)),
        patch("app.services.tasks.get_notice_for_ai_sync", return_value=mock_notice),
        patch("app.services.tasks.update_ai_result_sync", return_value=1) as mock_update,
        patch("app.services.tasks.extract_notice_info", return_value=envelope),
        patch("app.services.tasks._get_notice_html_for_content_url", return_value="<p>body</p>"),
    ):
        process_notice_ai_task.apply(args=(notice_id,), throw=True)

    mock_update.assert_called_once()
    call = mock_update.call_args
    ai_json = call[0][2]
    assert "category" in ai_json
    assert call[1]["dates"] is not None
    assert call[1]["eligibility"] is not None
    assert "taxonomy_rows" in call[1]
    assert call[1]["taxonomy_rows"] == []
    assert call[1].get("only_if_processing") is True


def test_process_notice_ai_task_fallback_notice_updates_with_fallback_envelope_meta() -> None:
    """fallback notice: envelope.status=fallback여도 update_ai_result_sync에 _envelope_meta 포함된 JSON 저장."""
    notice_id = str(uuid.uuid4())
    nid = uuid.UUID(notice_id)
    mock_notice = MagicMock()
    mock_notice.is_manual_edited = False
    mock_notice.title = "공지"
    mock_notice.notice_content = None
    mock_notice.images = None
    mock_notice.id = nid
    mock_college = MagicMock(name="단과대", external_id="x")
    mock_notice.college = mock_college

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

    s1, s2 = MagicMock(), MagicMock()
    with (
        patch("app.core.config.settings.ai_pipeline_enabled", True),
        patch("app.services.tasks.get_sync_session", side_effect=_multi_get_sync_session(s1, s2)),
        patch("app.services.tasks.get_notice_for_ai_sync", return_value=mock_notice),
        patch("app.services.tasks.update_ai_result_sync", return_value=1) as mock_update,
        patch("app.services.tasks.extract_notice_info", return_value=envelope),
        patch("app.services.tasks._get_notice_html_for_content_url", return_value="<p>body</p>"),
    ):
        process_notice_ai_task.apply(args=(notice_id,), throw=True)

    mock_update.assert_called_once()
    ai_json = mock_update.call_args[0][2]
    assert ai_json.get("metadata", {}).get("_envelope_meta", {}).get("fallback_reason") == "validation_error"


def test_process_notice_ai_task_provider_error_resets_pending_and_raises() -> None:
    """provider error: extract_notice_info 예외 시 pending 복구 후 예외 전파, 최종 update 없음."""
    notice_id = str(uuid.uuid4())
    nid = uuid.UUID(notice_id)
    mock_notice = MagicMock()
    mock_notice.is_manual_edited = False
    mock_notice.title = "공지"
    mock_notice.notice_content = None
    mock_notice.images = None
    mock_notice.id = nid
    mock_college = MagicMock(name="단과대", external_id="y")
    mock_notice.college = mock_college

    s1, s2 = MagicMock(), MagicMock()
    with (
        patch("app.core.config.settings.ai_pipeline_enabled", True),
        patch("app.services.tasks.get_sync_session", side_effect=_multi_get_sync_session(s1, s2)),
        patch("app.services.tasks.get_notice_for_ai_sync", return_value=mock_notice),
        patch("app.services.tasks.update_ai_result_sync") as mock_update,
        patch("app.services.tasks.extract_notice_info", side_effect=RequestException("network")),
        patch("app.services.tasks._get_notice_html_for_content_url", return_value="<p>body</p>"),
        patch(
            "app.services.tasks.reset_ai_notice_to_pending_after_failed_extraction_sync",
            return_value=1,
        ) as mock_reset,
        patch.object(process_notice_ai_task, "retry") as mock_retry,
    ):

        def _raise_original(exc=None, *args, **kwargs):
            raise exc or RequestException("network")

        mock_retry.side_effect = lambda *args, **kwargs: _raise_original(kwargs.get("exc"))
        with pytest.raises(RequestException):
            process_notice_ai_task.apply(args=(notice_id,), throw=True)

    mock_update.assert_not_called()
    mock_reset.assert_called_once()
    assert mock_reset.call_args[0][0] is s2
    assert mock_reset.call_args[0][1] == nid


def test_process_notice_ai_task_invalid_notice_id_returns_without_db() -> None:
    """UUID가 아닌 notice_id는 경고 후 종료(세션 미사용)."""
    with (
        patch("app.core.config.settings.ai_pipeline_enabled", True),
        patch("app.services.tasks.get_sync_session") as mock_session_ctx,
        patch("app.services.tasks.get_notice_for_ai_sync") as mock_get,
    ):
        process_notice_ai_task.apply(args=("not-a-uuid",), throw=True)
    mock_session_ctx.assert_not_called()
    mock_get.assert_not_called()


def test_process_notice_ai_task_missing_college_name_stores_fallback() -> None:
    """college.name 비어 있으면 LLM 호출 없이 폴백 투영으로 done 처리."""
    notice_id = str(uuid.uuid4())
    nid = uuid.UUID(notice_id)
    mock_notice = MagicMock()
    mock_notice.is_manual_edited = False
    mock_notice.title = "공지"
    mock_notice.notice_content = None
    mock_notice.images = None
    mock_notice.id = nid
    mock_college = MagicMock()
    mock_college.name = ""
    mock_college.external_id = "z"
    mock_notice.college = mock_college

    session = MagicMock()
    with (
        patch("app.core.config.settings.ai_pipeline_enabled", True),
        patch("app.services.tasks.get_sync_session", side_effect=_multi_get_sync_session(session)),
        patch("app.services.tasks.get_notice_for_ai_sync", return_value=mock_notice),
        patch("app.services.tasks.update_ai_result_sync", return_value=1) as mock_update,
        patch("app.services.tasks.extract_notice_info") as mock_extract,
        patch("app.services.tasks._get_notice_html_for_content_url", return_value="<p>x</p>"),
    ):
        process_notice_ai_task.apply(args=(notice_id,), throw=True)

    mock_extract.assert_not_called()
    mock_update.assert_called_once()
    ai_json = mock_update.call_args[0][2]
    assert ai_json.get("metadata", {}).get("_envelope_meta", {}).get("fallback_reason") == "missing_college_name"


def test_get_notice_html_for_content_url_reads_relative_local_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """상대 content_url은 로컬 content storage에서 실제 HTML을 읽는다."""
    from app.services.tasks import _get_notice_html_for_content_url

    content_base = tmp_path / "contents"
    html_path = content_base / "notice-contents" / "college" / "notice.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<p>참가대상: 대학생</p>", encoding="utf-8")
    monkeypatch.setattr("app.services.tasks.settings.content_storage_local_path", str(content_base))

    html = _get_notice_html_for_content_url("/notice-contents/college/notice.html", "제목")

    assert "참가대상: 대학생" in html


def test_get_notice_html_for_content_url_falls_back_to_notice_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """상대 content_url 파일이 로컬에 없으면 원문 notice.url을 fetch한다."""
    from app.services.tasks import _get_notice_html_for_content_url

    monkeypatch.setattr("app.services.tasks.settings.content_storage_local_path", "missing-storage-path")
    response = MagicMock()
    response.text = "<p>신청대상: 공과대학 재학생</p>"
    response.raise_for_status.return_value = None
    with patch("app.services.tasks.requests.get", return_value=response) as mock_get:
        html = _get_notice_html_for_content_url(
            "/notice-contents/missing.html",
            "제목",
            notice_url="https://engineering.yonsei.ac.kr/notice",
        )

    assert "신청대상: 공과대학 재학생" in html
    mock_get.assert_called_once()
