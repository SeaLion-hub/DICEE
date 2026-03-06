"""AI 파이프라인 스키마 투영·스키마 적용 검증."""

from app.schemas.ai import NoticeAIExtraction, NoticeCategory, ScheduleItem, ScheduleKind
from app.services.ai_pipeline import project_extraction_to_notice_fields


def test_project_extraction_to_notice_fields_stub():
    """스텁 NoticeAIExtraction을 DB 투영 필드 dict로 변환."""
    stub = NoticeAIExtraction(notice_category=NoticeCategory.OTHER)
    projected = project_extraction_to_notice_fields(stub)
    assert projected["ai_extracted_json"] is not None
    assert projected["ai_extracted_json"].get("notice_category") == "other"
    assert projected["dates"] == []
    assert projected["eligibility"] == []
    assert projected["hashtags"] == []
    assert projected["category"] == "other"


def test_project_extraction_to_notice_fields_with_schedules():
    """schedules가 있으면 dates에 직렬화된 list[dict]로 투영."""
    extraction = NoticeAIExtraction(
        notice_category=NoticeCategory.RECRUITMENT,
        schedules=[
            ScheduleItem(kind=ScheduleKind.APPLICATION_DEADLINE, label="서류 마감"),
            ScheduleItem(kind=ScheduleKind.INTERVIEW, label="1차 면접", date_raw="11월 중순"),
        ],
        eligibility_rules=["3학년 이상", "전공 무관"],
        hashtags=["장학금", "인턴"],
    )
    projected = project_extraction_to_notice_fields(extraction)
    assert projected["category"] == "recruitment"
    assert len(projected["dates"]) == 2
    assert projected["dates"][0]["kind"] == "application_deadline"
    assert projected["dates"][0]["label"] == "서류 마감"
    assert projected["dates"][1]["date_raw"] == "11월 중순"
    assert projected["eligibility"] == ["3학년 이상", "전공 무관"]
    assert projected["hashtags"] == ["장학금", "인턴"]
    assert "raw_eligibility_text" in projected["ai_extracted_json"]
