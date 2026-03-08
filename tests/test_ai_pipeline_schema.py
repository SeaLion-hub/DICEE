"""AI 파이프라인 스키마 투영·스키마 적용 검증."""

from unittest.mock import patch

from app.schemas.ai import NoticeAIExtraction, NoticeCategory, ScheduleItem, ScheduleKind
from app.services.ai_pipeline import extract_notice_info, project_extraction_to_notice_fields


def test_project_extraction_to_notice_fields_stub():
    """스텁 NoticeAIExtraction을 DB 투영 필드 dict로 변환."""
    stub = NoticeAIExtraction()
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
        schedules=[
            ScheduleItem(kind=ScheduleKind.APPLICATION_DEADLINE, label="서류 마감"),
            ScheduleItem(kind=ScheduleKind.INTERVIEW, label="1차 면접", date_raw="11월 중순"),
        ],
        eligibility_rules=["3학년 이상", "전공 무관"],
        hashtags=["장학금", "인턴"],
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
    """extract_notice_info는 image_urls를 extract_notice_structured에 그대로 전달."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    stub = NoticeAIExtraction()
    with patch(
        "app.services.ai_pipeline.extract_notice_structured",
        return_value=stub,
    ) as mock_extract:
        result = extract_notice_info("<p>html</p>", image_urls=["https://example.com/img.png"])
    assert result is stub
    mock_extract.assert_called_once()
    call_kw = mock_extract.call_args[1]
    assert call_kw.get("image_urls") == ["https://example.com/img.png"]


def test_extract_notice_info_passes_empty_image_urls():
    """image_urls=None이면 extract_notice_structured에 None 전달."""
    from app.domain.contracts.ai_extraction import NoticeAIExtraction

    stub = NoticeAIExtraction()
    with patch(
        "app.services.ai_pipeline.extract_notice_structured",
        return_value=stub,
    ) as mock_extract:
        result = extract_notice_info("<p>html</p>")
    assert result is stub
    mock_extract.assert_called_once_with("<p>html</p>", image_urls=None)
