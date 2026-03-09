"""AI 파이프라인 스키마 투영·스키마 적용 검증."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError
from requests.exceptions import RequestException

from app.schemas.ai import NoticeAIExtraction, NoticeCategory, ScheduleItem, ScheduleKind
from app.domain.contracts.ai_extraction import (
    NoticeAIExtraction as DomainNoticeAIExtraction,
)
from app.services.ai_pipeline import (
    extract_notice_info,
    project_extraction_to_notice_fields,
    validate_extraction_raw_substrings,
)
from app.core.config import settings


def test_project_extraction_to_notice_fields_stub():
    """스텁 NoticeAIExtraction을 DB 투영 필드 dict로 변환."""
    stub = NoticeAIExtraction(target_departments=[])
    projected = project_extraction_to_notice_fields(stub)
    assert projected["ai_extracted_json"] is not None
    assert "notice_category" not in projected["ai_extracted_json"]
    assert projected["dates"] == []
    assert projected["eligibility"] == []
    assert projected["hashtags"] == []
    assert projected["category"] == NoticeCategory.OTHER.value
    assert projected["sub_category"] is None


def test_project_extraction_to_notice_fields_with_schedules():
    """schedules가 있으면 dates에 직렬화된 list[dict]로 투영. category/sub_category 포함."""
    extraction = NoticeAIExtraction(
        category=NoticeCategory.SCHOLARSHIP,
        sub_category="국가장학금",
        raw_eligibility_text="3학년 이상 전공 무관 지원 가능",
        schedules=[
            ScheduleItem(
                kind=ScheduleKind.APPLICATION_DEADLINE,
                label="서류 마감",
                date_raw="11월 초",
            ),
            ScheduleItem(kind=ScheduleKind.INTERVIEW, label="1차 면접", date_raw="11월 중순"),
        ],
        eligibility_rules=["3학년 이상", "전공 무관"],
        hashtags=["장학금", "인턴"],
        target_departments=["컴퓨터공학과"],
    )
    projected = project_extraction_to_notice_fields(extraction)
    assert projected["category"] == "scholarship"
    assert projected["sub_category"] == "국가장학금"
    assert len(projected["dates"]) == 2
    assert projected["dates"][0]["kind"] == "application_deadline"
    assert projected["dates"][0]["label"] == "서류 마감"
    assert projected["dates"][1]["date_raw"] == "11월 중순"
    assert projected["eligibility"] == ["3학년 이상", "전공 무관"]
    assert projected["hashtags"] == ["장학금", "인턴"]
    assert "raw_eligibility_text" in projected["ai_extracted_json"]


def test_extract_notice_info_passes_image_urls():
    """extract_notice_info는 image_urls를 extract_notice_structured_with_usage에 그대로 전달."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    stub = NoticeAIExtraction(target_departments=[])
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        return_value=(stub, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
    ) as mock_extract:
        result = extract_notice_info("<p>html</p>", image_urls=["https://example.com/img.png"])
    assert result.result is stub
    mock_extract.assert_called_once()
    call_kw = mock_extract.call_args[1]
    assert call_kw.get("image_urls") == ["https://example.com/img.png"]


def test_extract_notice_info_passes_empty_image_urls():
    """image_urls=None이면 extract_notice_structured_with_usage에 None 전달."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    stub = NoticeAIExtraction(target_departments=[])
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        return_value=(stub, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
    ) as mock_extract:
        result = extract_notice_info("<p>html</p>")
    assert result.result is stub
    mock_extract.assert_called_once_with("html", image_urls=None)


def test_project_extraction_to_notice_fields_includes_envelope_meta() -> None:
    """ExtractionEnvelope 메타데이터가 ai_extracted_json.metadata에 네임스페이스로 저장된다."""
    stub = NoticeAIExtraction(target_departments=[])
    meta = {
        "pipeline_version": "v1",
        "provider": "google/gemini-1.5-flash",
        "model": "gemini-1.5-flash",
        "fallback_reason": "validation_error",
        "html_raw_len": 123,
        "html_clean_len": 100,
        "image_count": 2,
        "elapsed_ms": 42,
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
    }
    projected = project_extraction_to_notice_fields(stub, envelope_meta=meta)
    raw = projected["ai_extracted_json"]
    assert "metadata" in raw
    assert "_envelope_meta" in raw["metadata"]
    assert raw["metadata"]["_envelope_meta"]["pipeline_version"] == "v1"
    assert raw["metadata"]["_envelope_meta"]["provider"] == "google/gemini-1.5-flash"
    assert raw["metadata"]["_envelope_meta"]["model"] == "gemini-1.5-flash"
    assert raw["metadata"]["_envelope_meta"]["fallback_reason"] == "validation_error"
    assert raw["metadata"]["_envelope_meta"]["html_raw_len"] == 123
    assert raw["metadata"]["_envelope_meta"]["html_clean_len"] == 100
    assert raw["metadata"]["_envelope_meta"]["image_count"] == 2
    assert raw["metadata"]["_envelope_meta"]["elapsed_ms"] == 42
    usage = raw["metadata"]["_envelope_meta"]["usage"]
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 20
    assert usage["total_tokens"] == 30


def test_extract_notice_info_validation_error_produces_fallback_envelope() -> None:
    """ValidationError 발생 시 status=fallback과 올바른 fallback_reason/meta가 설정된다."""

    def _raise_validation_error(*args, **kwargs):
        raise ValidationError.from_exception_data("NoticeAIExtraction", [])

    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        side_effect=_raise_validation_error,
    ):
        envelope = extract_notice_info("<p>html</p>")

    assert envelope.status == "fallback"
    assert envelope.meta["fallback_reason"] == "validation_error"
    assert envelope.meta["html_raw_len"] == len("<p>html</p>")
    # _clean_notice_html는 태그를 제거해 "html"을 반환하므로 길이는 4이다.
    assert envelope.meta["html_clean_len"] == 4
    assert "elapsed_ms" in envelope.meta
    assert "image_count" in envelope.meta
    assert envelope.meta["provider"] == f"google/{settings.gemini_model}"
    assert envelope.meta["model"] == settings.gemini_model
    # usage는 표준 키를 모두 포함해야 한다.
    assert set(envelope.usage.keys()) == {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }


def test_extract_notice_info_unexpected_error_is_propagated() -> None:
    """검증 계열이 아닌 예외는 fallback으로 변환되지 않고 그대로 전파된다."""

    def _raise_runtime_error(*args, **kwargs):
        raise RuntimeError("boom")

    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        side_effect=_raise_runtime_error,
    ):
        with pytest.raises(RuntimeError):
            extract_notice_info("<p>html</p>")


def test_extract_notice_info_instructor_retry_exception_produces_fallback_envelope() -> None:
    """InstructorRetryException (재시도 소진) 발생 시 validation 계열 fallback으로 처리된다."""
    instructor_exceptions = pytest.importorskip("instructor.core.exceptions")
    InstructorRetryException = instructor_exceptions.InstructorRetryException

    def _raise_retry_exhausted(*args, **kwargs):
        raise InstructorRetryException(
            "retry exhausted",
            n_attempts=3,
            total_usage={},
        )

    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        side_effect=_raise_retry_exhausted,
    ):
        envelope = extract_notice_info("<p>html</p>")

    assert envelope.status == "fallback"
    assert envelope.meta["fallback_reason"] == "validation_retry_exhausted"


def test_extract_notice_info_provider_error_is_propagated() -> None:
    """네트워크/프로바이더 계열 예외(RequestException)는 fallback으로 변환되지 않고 그대로 전파된다."""

    def _raise_request_exception(*args, **kwargs):
        raise RequestException("network error")

    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        side_effect=_raise_request_exception,
    ):
        with pytest.raises(RequestException):
            extract_notice_info("<p>html</p>")


def test_extract_notice_info_success_meta_includes_provider() -> None:
    """성공 경로에서도 provider/model 및 표준 usage 메타데이터가 포함된다."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    stub = NoticeAIExtraction(target_departments=[])
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        return_value=(stub, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
    ):
        envelope = extract_notice_info("<p>html</p>")

    assert envelope.status == "ok"
    assert envelope.meta["provider"] == f"google/{settings.gemini_model}"
    assert envelope.meta["model"] == settings.gemini_model
    assert "html_raw_len" in envelope.meta
    assert "html_clean_len" in envelope.meta
    assert "image_count" in envelope.meta
    assert "elapsed_ms" in envelope.meta
    assert envelope.meta["fallback_reason"] is None
    # usage 표준 키 존재 여부 확인
    assert set(envelope.usage.keys()) == {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }


def test_ai_extracted_json_round_trips_through_notice_ai_extraction() -> None:
    """저장된 ai_extracted_json은 NoticeAIExtraction 스키마로 round-trip 가능해야 한다."""
    stub = DomainNoticeAIExtraction(
        category=NoticeCategory.SCHOLARSHIP.value,  # type: ignore[arg-type]
        sub_category="국가장학금",
        raw_eligibility_text="요건 원문",
        eligibility_rules=["rule-1"],
        target_departments=["컴퓨터공학과"],
        hashtags=["장학금"],
    )
    meta = {
        "pipeline_version": "v1",
        "provider": "google/gemini-1.5-flash",
        "model": "gemini-1.5-flash",
        "fallback_reason": None,
        "html_raw_len": 1000,
        "html_clean_len": 800,
        "image_count": 1,
        "elapsed_ms": 10,
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
    projected = project_extraction_to_notice_fields(stub, envelope_meta=meta)
    raw = projected["ai_extracted_json"]

    # extra="forbid" 스키마에서도 ValidationError 없이 복원 가능해야 한다.
    restored = DomainNoticeAIExtraction.model_validate(raw)
    assert restored.category == stub.category
    assert restored.sub_category == stub.sub_category
    assert restored.hashtags == stub.hashtags
    assert restored.metadata.get("_envelope_meta") == meta


def test_validate_extraction_raw_substrings_pass() -> None:
    """raw_eligibility_text가 source에 포함되면 검증 통과."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    extraction = NoticeAIExtraction(
        raw_eligibility_text="3학년 이상 전공 무관",
        target_departments=[],
    )
    validate_extraction_raw_substrings(
        extraction, "본문 내용. 3학년 이상 전공 무관 지원 가능."
    )


def test_validate_extraction_raw_substrings_fail() -> None:
    """raw_eligibility_text가 source에 없으면 ValueError."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    extraction = NoticeAIExtraction(
        raw_eligibility_text="환각된 문장 없음",
        target_departments=[],
    )
    with pytest.raises(ValueError, match="substring"):
        validate_extraction_raw_substrings(extraction, "완전히 다른 본문")


def test_extract_notice_info_raw_substring_validation_fallback(monkeypatch) -> None:
    """ai_extraction_enforce_raw_substrings=True이고 raw가 원문에 없으면 fallback 반환."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    monkeypatch.setattr(settings, "ai_extraction_enforce_raw_substrings", True)
    stub = NoticeAIExtraction(
        raw_eligibility_text="원문에 없는 문구",
        target_departments=[],
    )
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        return_value=(stub, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
    ):
        envelope = extract_notice_info("<p>짧은 본문</p>")
    assert envelope.status == "fallback"
    assert envelope.meta["fallback_reason"] == "raw_substring_validation_failed"


def test_extract_notice_info_multimodal_skips_raw_substring_validation(monkeypatch) -> None:
    """이미지가 있으면 raw substring 검증을 건너뛰어, 이미지에서만 읽은 정상 추출이 거짓 fallback되지 않는다."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    monkeypatch.setattr(settings, "ai_extraction_enforce_raw_substrings", True)
    stub = NoticeAIExtraction(
        raw_eligibility_text="포스터에만 있는 자격 문구",
        target_departments=[],
    )
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        return_value=(stub, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
    ):
        envelope = extract_notice_info(
            "<p>본문만 있는 HTML</p>",
            image_urls=["https://example.com/poster.png"],
        )
    assert envelope.status == "ok"
    assert envelope.result is stub
