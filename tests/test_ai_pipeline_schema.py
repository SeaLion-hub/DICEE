"""AI 파이프라인 스키마 투영·스키마 적용 검증."""

from unittest.mock import patch

import pytest
from app.core.config import settings
from app.domain.contracts.ai_extraction import (
    NoticeAIExtraction as DomainNoticeAIExtraction,
)
from app.domain.contracts.ai_extraction import (
    NoticeMainCategory,
    TaxonomyMappingItem,
)
from app.schemas.ai import NoticeAIExtraction, NoticeCategory, ScheduleItem, ScheduleKind
from app.services.ai.exceptions import AIProviderRetryableError
from app.services.ai.extractor import (
    EXTRACTOR_SYSTEM_PROMPT,
    MAIN_CATEGORY_SYSTEM_PROMPT,
    apply_vision_image_gate,
    extract_notice_structured_with_usage,
)
from app.services.ai.types import ExtractorCallStats, TokenUsage
from app.services.ai_pipeline import (
    extract_notice_info,
    project_extraction_to_notice_fields,
    validate_and_normalize_taxonomy,
    validate_extraction_raw_substrings,
)
from pydantic import ValidationError
from requests.exceptions import RequestException


def test_project_extraction_to_notice_fields_stub():
    """스텁 NoticeAIExtraction을 DB 투영 필드 dict로 변환."""
    stub = NoticeAIExtraction(target_departments=[])
    projected = project_extraction_to_notice_fields(stub)
    assert projected["ai_extracted_json"] is not None
    assert "notice_category" not in projected["ai_extracted_json"]
    assert projected["dates"] == []
    assert projected["eligibility"] == []
    assert projected["hashtags"] == []
    assert projected["taxonomy_rows"] == []


def test_project_extraction_to_notice_fields_with_schedules():
    """schedules 및 taxonomy_mappings가 있으면 dates/taxonomy_rows로 투영한다."""
    extraction = NoticeAIExtraction(
        category=NoticeCategory.SCHOLARSHIP,
        sub_category="국가장학금",
        main_categories=[NoticeMainCategory.SCHOLARSHIP_SUPPORT],
        taxonomy_mappings=[
            TaxonomyMappingItem(
                main_category=NoticeMainCategory.SCHOLARSHIP_SUPPORT,
                sub_categories=["교내/성적장학", "외부장학"],
            )
        ],
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
    assert len(projected["dates"]) == 2
    assert projected["dates"][0]["kind"] == "application_deadline"
    assert projected["dates"][0]["label"] == "서류 마감"
    assert projected["dates"][1]["date_raw"] == "11월 중순"
    assert projected["eligibility"] == ["3학년 이상", "전공 무관"]
    assert projected["hashtags"] == ["장학금", "인턴"]
    assert projected["taxonomy_rows"] == [
        {"main_category": "장학/지원", "sub_category": "교내/성적장학"},
        {"main_category": "장학/지원", "sub_category": "외부장학"},
    ]
    assert "raw_eligibility_text" in projected["ai_extracted_json"]


def test_extract_notice_info_passes_image_urls():
    """extract_notice_info는 image_urls를 extract_notice_structured_with_usage에 그대로 전달."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    stub = NoticeAIExtraction(target_departments=[])
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        return_value=(stub, TokenUsage(), ExtractorCallStats()),
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
        return_value=(stub, TokenUsage(), ExtractorCallStats()),
    ) as mock_extract:
        result = extract_notice_info("<p>html</p>")
    assert result.result is stub
    mock_extract.assert_called_once()
    assert mock_extract.call_args[0][0] == "<p>html</p>"
    assert mock_extract.call_args[1].get("image_urls") is None
    assert mock_extract.call_args[1].get("model") == settings.gemini_model


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
    assert envelope.meta.fallback_reason == "validation_error"
    assert envelope.meta.html_raw_len == len("<p>html</p>")
    # _clean_notice_html는 slim_html을 반환하므로 "<p>html</p>" 길이(11)를 유지한다.
    assert envelope.meta.html_clean_len == len("<p>html</p>")
    assert envelope.meta.elapsed_ms >= 0
    assert envelope.meta.image_count == 0
    assert envelope.meta.provider == f"google/{settings.gemini_model}"
    assert envelope.meta.model == settings.gemini_model
    assert envelope.usage == TokenUsage()


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
    instructor_retry_exc_cls = instructor_exceptions.InstructorRetryException

    def _raise_retry_exhausted(*args, **kwargs):
        raise instructor_retry_exc_cls(
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
    assert envelope.meta.fallback_reason == "validation_retry_exhausted"


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


def test_extract_notice_info_instructor_429_raises_retryable_provider_error() -> None:
    instructor_exceptions = pytest.importorskip("instructor.core.exceptions")
    instructor_retry_exc_cls = instructor_exceptions.InstructorRetryException

    def _raise_rate_limited(*args, **kwargs):
        raise instructor_retry_exc_cls(
            "RESOURCE_EXHAUSTED 429 quota exceeded",
            n_attempts=3,
            total_usage={},
        )

    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        side_effect=_raise_rate_limited,
    ):
        with pytest.raises(AIProviderRetryableError):
            extract_notice_info("<p>html</p>")


def test_extract_notice_info_token_limit_retries_once_then_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def _raise_token_limit(html_content: str, *args, **kwargs):
        calls.append(len(html_content))
        raise RuntimeError("context length token limit exceeded")

    monkeypatch.setattr(settings, "ai_extraction_token_limit_retry_char_limit", 500)
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        side_effect=_raise_token_limit,
    ):
        envelope = extract_notice_info("<p>" + ("x" * 2000) + "</p>")

    assert envelope.status == "fallback"
    assert envelope.meta.fallback_reason == "token_limit_exhausted"
    assert len(calls) == 2
    assert calls[1] == 500


def test_extract_notice_info_success_meta_includes_provider() -> None:
    """성공 경로에서도 provider/model 및 표준 usage 메타데이터가 포함된다."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    stub = NoticeAIExtraction(target_departments=[])
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        return_value=(stub, TokenUsage(), ExtractorCallStats()),
    ):
        envelope = extract_notice_info("<p>html</p>")

    assert envelope.status == "ok"
    assert envelope.meta.provider == f"google/{settings.gemini_model}"
    assert envelope.meta.model == settings.gemini_model
    assert envelope.meta.html_raw_len == len("<p>html</p>")
    assert envelope.meta.html_clean_len >= 0
    assert envelope.meta.image_count == 0
    assert envelope.meta.elapsed_ms >= 0
    assert envelope.meta.fallback_reason is None
    assert envelope.usage == TokenUsage()


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
    validate_extraction_raw_substrings(extraction, "본문 내용. 3학년 이상 전공 무관 지원 가능.")


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
        return_value=(stub, TokenUsage(), ExtractorCallStats()),
    ):
        envelope = extract_notice_info("<p>짧은 본문</p>")
    assert envelope.status == "fallback"
    assert envelope.meta.fallback_reason == "raw_substring_validation_failed"


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
        return_value=(stub, TokenUsage(), ExtractorCallStats()),
    ):
        envelope = extract_notice_info(
            "<p>본문만 있는 HTML</p>",
            image_urls=["https://example.com/poster.png"],
        )
    assert envelope.status == "ok"
    assert envelope.result is stub


def test_validate_and_normalize_taxonomy_allows_unclassified_empty_main() -> None:
    """main_categories가 비어 있으면 미분류 정책으로 통과시킨다."""
    extraction = NoticeAIExtraction(target_departments=[])
    normalized = validate_and_normalize_taxonomy(extraction)
    assert normalized is extraction


def test_validate_and_normalize_taxonomy_deduplicates_sub_categories() -> None:
    """taxonomy 후처리에서 소분류 공백/중복을 정리한다."""
    mapping = TaxonomyMappingItem.model_construct(
        main_category=NoticeMainCategory.SCHOLARSHIP_SUPPORT,
        sub_categories=["교내/성적장학", "교내/성적장학", " ", "외부장학"],
    )
    extraction = DomainNoticeAIExtraction.model_construct(
        main_categories=[NoticeMainCategory.SCHOLARSHIP_SUPPORT],
        taxonomy_mappings=[mapping],
        target_departments=[],
    )
    normalized = validate_and_normalize_taxonomy(extraction)
    assert normalized.taxonomy_mappings[0].sub_categories == ["교내/성적장학", "외부장학"]


def test_extract_notice_info_taxonomy_validation_degrades_preserves_rest() -> None:
    """taxonomy 구조 위반 시 대분류·매핑만 비우고 일정·자격 등 나머지는 유지한다."""
    invalid_extraction = DomainNoticeAIExtraction.model_construct(
        main_categories=[NoticeMainCategory.CAREER_EMPLOYMENT],
        taxonomy_mappings=[],
        target_departments=[],
        raw_eligibility_text="본문 발췌 자격",
        eligibility_rules=["본문 발췌 자격"],
        schedules=[
            ScheduleItem(
                kind=ScheduleKind.APPLICATION_DEADLINE,
                label="서류 마감",
                date_raw="4월 10일",
            ),
        ],
    )
    with patch(
        "app.services.ai_pipeline.extract_notice_structured_with_usage",
        return_value=(invalid_extraction, TokenUsage(), ExtractorCallStats()),
    ):
        envelope = extract_notice_info("<p>html</p>")
    assert envelope.status == "ok"
    assert envelope.meta.taxonomy_degraded is True
    assert envelope.result.main_categories == []
    assert envelope.result.taxonomy_mappings == []
    assert envelope.result.raw_eligibility_text == "본문 발췌 자격"
    assert len(envelope.result.schedules) == 1
    assert envelope.result.metadata.get("taxonomy_degraded") is True


def test_taxonomy_case_overseas_scholarship_multi_label_pass() -> None:
    """해외 파견 장학생 모집: 국제/교류 + 장학/지원 조합은 유효해야 한다."""
    extraction = DomainNoticeAIExtraction(
        main_categories=[
            NoticeMainCategory.INTERNATIONAL_EXCHANGE,
            NoticeMainCategory.SCHOLARSHIP_SUPPORT,
        ],
        taxonomy_mappings=[
            TaxonomyMappingItem(
                main_category=NoticeMainCategory.INTERNATIONAL_EXCHANGE,
                sub_categories=["교환/방문학생"],
            ),
            TaxonomyMappingItem(
                main_category=NoticeMainCategory.SCHOLARSHIP_SUPPORT,
                sub_categories=["외부장학"],
            ),
        ],
        target_departments=[],
    )
    normalized = validate_and_normalize_taxonomy(extraction)
    assert {c.value for c in normalized.main_categories} == {"국제/교류", "장학/지원"}


def test_taxonomy_case_global_startup_hackathon_multi_label_pass() -> None:
    """글로벌 창업 해커톤: 국제/교류 + 진로/취업 + 대회/공모전 조합은 유효해야 한다."""
    extraction = DomainNoticeAIExtraction(
        main_categories=[
            NoticeMainCategory.INTERNATIONAL_EXCHANGE,
            NoticeMainCategory.CAREER_EMPLOYMENT,
            NoticeMainCategory.CONTEST_COMPETITION,
        ],
        taxonomy_mappings=[
            TaxonomyMappingItem(
                main_category=NoticeMainCategory.INTERNATIONAL_EXCHANGE,
                sub_categories=["단기연수/캠프"],
            ),
            TaxonomyMappingItem(
                main_category=NoticeMainCategory.CAREER_EMPLOYMENT,
                sub_categories=["창업지원"],
            ),
            TaxonomyMappingItem(
                main_category=NoticeMainCategory.CONTEST_COMPETITION,
                sub_categories=["해커톤/아이디어"],
            ),
        ],
        target_departments=[],
    )
    normalized = validate_and_normalize_taxonomy(extraction)
    assert {c.value for c in normalized.main_categories} == {
        "국제/교류",
        "진로/취업",
        "대회/공모전",
    }


def test_taxonomy_case_dongari_expo_as_campus_life_fails() -> None:
    """동아리 박람회를 캠퍼스생활로 잘못 매핑(교차 소분류)하면 실패해야 한다."""
    invalid = DomainNoticeAIExtraction.model_construct(
        main_categories=[NoticeMainCategory.CAMPUS_LIFE],
        taxonomy_mappings=[
            TaxonomyMappingItem.model_construct(
                main_category=NoticeMainCategory.CAMPUS_LIFE,
                sub_categories=["동아리/학생회"],
            )
        ],
        target_departments=[],
    )
    with pytest.raises(ValueError):
        validate_and_normalize_taxonomy(invalid)


def test_taxonomy_case_wifi_notice_campus_life_single_pass() -> None:
    """Wi-Fi 점검 안내는 캠퍼스생활 단일 + IT/시스템안내로 통과해야 한다."""
    extraction = DomainNoticeAIExtraction(
        main_categories=[NoticeMainCategory.CAMPUS_LIFE],
        taxonomy_mappings=[
            TaxonomyMappingItem(
                main_category=NoticeMainCategory.CAMPUS_LIFE,
                sub_categories=["IT/시스템안내"],
            )
        ],
        target_departments=[],
    )
    normalized = validate_and_normalize_taxonomy(extraction)
    assert [c.value for c in normalized.main_categories] == ["캠퍼스생활"]
    assert normalized.taxonomy_mappings[0].sub_categories == ["IT/시스템안내"]


def test_taxonomy_case_mixed_unselected_parent_subcategory_fails() -> None:
    """선택되지 않은 부모의 소분류가 섞이면(main set 불일치) 실패해야 한다."""
    invalid = DomainNoticeAIExtraction.model_construct(
        main_categories=[NoticeMainCategory.SCHOLARSHIP_SUPPORT],
        taxonomy_mappings=[
            TaxonomyMappingItem.model_construct(
                main_category=NoticeMainCategory.SCHOLARSHIP_SUPPORT,
                sub_categories=["교내/성적장학"],
            ),
            TaxonomyMappingItem.model_construct(
                main_category=NoticeMainCategory.INTERNATIONAL_EXCHANGE,
                sub_categories=["어학프로그램"],
            ),
        ],
        target_departments=[],
    )
    with pytest.raises(ValueError, match="same set of main categories"):
        validate_and_normalize_taxonomy(invalid)


def test_single_pass_extraction_requires_title_and_college_name() -> None:
    """단일 패스 추출은 title/college_name 필수."""
    with pytest.raises(ValueError, match="title is required"):
        extract_notice_structured_with_usage(
            "<p>본문</p>",
            image_urls=["https://example.com/poster.png"],
            title=None,
            college_name="공과대학",
        )
    with pytest.raises(ValueError, match="college_name is required"):
        extract_notice_structured_with_usage(
            "<p>본문</p>",
            image_urls=["https://example.com/poster.png"],
            title="테스트 공지",
            college_name=None,
        )


def test_single_pass_extraction_requires_body_or_image() -> None:
    """본문/이미지가 모두 없으면 추출 불가."""
    with pytest.raises(ValueError, match="html_content or image_urls is required"):
        extract_notice_structured_with_usage(
            "",
            image_urls=[],
            title="테스트 공지",
            college_name="경영대학",
        )


def test_legacy_main_category_prompt_documented() -> None:
    """레거시 1단계 전용 프롬프트(참고용)에 허용 대분류·캠퍼스생활 배타가 있다."""
    assert "<ALLOWED_MAIN_CATEGORIES>" in MAIN_CATEGORY_SYSTEM_PROMPT
    assert "오직 [제목]과 [college.name(발신 기관명)]" in MAIN_CATEGORY_SYSTEM_PROMPT
    assert "캠퍼스생활 배타 게이트" in MAIN_CATEGORY_SYSTEM_PROMPT
    assert '["캠퍼스생활"]' in MAIN_CATEGORY_SYSTEM_PROMPT


def test_unified_extractor_prompt_single_pass_taxonomy() -> None:
    """단일 패스 추출 프롬프트는 대분류 규칙·taxonomy 풀·main/taxonomy 일관성을 명시한다."""
    assert "preselected_main_categories" not in EXTRACTOR_SYSTEM_PROMPT
    assert "<ALLOWED_MAIN_CATEGORIES>" in EXTRACTOR_SYSTEM_PROMPT
    assert "캠퍼스생활 배타 게이트" in EXTRACTOR_SYSTEM_PROMPT
    assert "<TAXONOMY_POOL>" in EXTRACTOR_SYSTEM_PROMPT
    assert "main_categories와 taxonomy_mappings" in EXTRACTOR_SYSTEM_PROMPT


def test_apply_vision_gate_image_only_uses_active_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """본문이 비어 이미지만 있으면 Vision 게이트를 열고 active cap까지 URL을 넘긴다."""
    monkeypatch.setattr(settings, "ai_vision_gate_enabled", True)
    monkeypatch.setattr(settings, "ai_vision_max_images_active", 5)
    urls = [f"https://example.com/{i}.png" for i in range(7)]
    gated, used = apply_vision_image_gate("", urls, "제목")
    assert used is True
    assert len(gated) == 5


def test_apply_vision_gate_long_html_respects_passive_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """긴 본문이면 passive cap(기본 0)으로 Vision을 끈다."""
    monkeypatch.setattr(settings, "ai_vision_gate_enabled", True)
    monkeypatch.setattr(settings, "ai_vision_body_char_threshold", 50)
    monkeypatch.setattr(settings, "ai_vision_max_images_passive", 0)
    html = "<p>" + ("x" * 200) + "</p>"
    gated, used = apply_vision_image_gate(html, ["https://example.com/a.png"], "일반 안내")
    assert gated == []
    assert used is False


def test_apply_vision_gate_disabled_passes_up_to_five(monkeypatch: pytest.MonkeyPatch) -> None:
    """게이트 비활성 시 기존처럼 최대 5장까지 전달한다."""
    monkeypatch.setattr(settings, "ai_vision_gate_enabled", False)
    urls = [f"https://e.com/{i}.jpg" for i in range(8)]
    gated, used = apply_vision_image_gate("<p>짧음</p>", urls, "t")
    assert len(gated) == 5
    assert used is True
