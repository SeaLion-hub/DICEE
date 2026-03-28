from datetime import datetime, timedelta, timezone

import pytest
from app.domain.contracts.ai_extraction import (
    NoticeAIExtraction,
    ScheduleItem,
    ScheduleKind,
)
from pydantic import ValidationError


def test_schedule_item_requires_some_date_field() -> None:
    """ScheduleItem는 최소 한 개의 날짜/원문 필드를 요구한다."""
    with pytest.raises(ValidationError):
        ScheduleItem(
            kind=ScheduleKind.APPLICATION_DEADLINE,
            label="서류 마감",
        )


def test_schedule_item_start_before_end() -> None:
    """starts_at > ends_at 이면 ValidationError."""
    tz = timezone(timedelta(hours=9))
    starts = datetime(2026, 3, 10, 12, 0, tzinfo=tz)
    ends = datetime(2026, 3, 9, 12, 0, tzinfo=tz)

    with pytest.raises(ValidationError):
        ScheduleItem(
            kind=ScheduleKind.EVENT,
            label="역순 일정",
            starts_at=starts,
            ends_at=ends,
        )


def test_schedule_item_date_raw_exclusive_with_start_end_raw() -> None:
    """date_raw는 start_date_raw/end_date_raw와 함께 사용할 수 없다."""
    with pytest.raises(ValidationError):
        ScheduleItem(
            kind=ScheduleKind.EVENT,
            label="모호 일정",
            date_raw="11월 중순",
            start_date_raw="11월 초",
        )


def test_eligibility_rules_require_raw_text() -> None:
    """eligibility 관련 필드는 raw_eligibility_text 없이 채울 수 없다."""
    with pytest.raises(ValidationError):
        NoticeAIExtraction(
            eligibility_rules=["3학년 이상"],
            target_departments=[],
        )


def test_hashtags_normalization_deduplicates_and_limits() -> None:
    """해시태그는 공백/중복/플레이스홀더를 정규화하고 개수를 제한한다."""
    extraction = NoticeAIExtraction(
        hashtags=[" 장학금 ", "장학금", "N/A", "na", "인턴", "인턴 ", "  ", "SCHOLARSHIP"],
        target_departments=[],
    )
    # placeholder와 공백/중복 제거 후 소수의 태그만 남아야 한다.
    assert "장학금" in extraction.hashtags
    assert "인턴" in extraction.hashtags
    # 대소문자 중복은 제거되어야 한다.
    assert len(extraction.hashtags) <= 4


def test_scalar_string_inputs_for_list_fields_raise_validation_error() -> None:
    """리스트 필드는 잘못된 스칼라 문자열 입력을 거부해야 한다."""
    with pytest.raises(ValidationError):
        NoticeAIExtraction(eligibility_rules="장학금")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        NoticeAIExtraction(target_departments="전 학과")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        NoticeAIExtraction(hashtags="장학금")  # type: ignore[arg-type]


def test_non_string_items_in_list_fields_raise_validation_error() -> None:
    """리스트 안의 비문자 항목은 ValidationError로 처리되어야 한다."""
    with pytest.raises(ValidationError):
        NoticeAIExtraction(eligibility_rules=["ok", 1])  # type: ignore[list-item]
    with pytest.raises(ValidationError):
        NoticeAIExtraction(
            raw_eligibility_text="요건 원문",
            target_departments=["컴퓨터공학과", 123],  # type: ignore[list-item]
        )
    with pytest.raises(ValidationError):
        NoticeAIExtraction(hashtags=["장학금", 999])  # type: ignore[list-item]


def test_hashtags_korean_and_english_placeholders_removed() -> None:
    """해시태그에서 한국어/영어 placeholder는 모두 제거된다."""
    extraction = NoticeAIExtraction(
        hashtags=["없음", " N/A ", "해당없음", "  ", "장학금"],
        target_departments=[],
    )
    assert extraction.hashtags == ["장학금"]


def test_eligibility_rules_limited_to_max_items() -> None:
    """eligibility_rules는 상한 개수까지만 유지한다."""
    rules = [f"rule-{i}" for i in range(30)]
    extraction = NoticeAIExtraction(
        raw_eligibility_text="요건 원문",
        eligibility_rules=rules,
        target_departments=[],
    )
    assert len(extraction.eligibility_rules) == 20
    assert extraction.eligibility_rules == rules[:20]


def test_target_departments_limited_to_max_items() -> None:
    """target_departments도 상한 개수까지만 유지한다."""
    departments = [f"학과{i}" for i in range(60)]
    extraction = NoticeAIExtraction(
        raw_eligibility_text="요건 원문",
        target_departments=departments,
    )
    assert len(extraction.target_departments) == 50
    assert extraction.target_departments == departments[:50]


def test_target_grades_limited_to_max_items() -> None:
    """target_grades는 상한 개수까지만 유지한다."""
    from app.domain.contracts.ai_extraction import TargetGrade

    grades = [TargetGrade.ONE, TargetGrade.TWO, TargetGrade.THREE] * 8
    extraction = NoticeAIExtraction(
        raw_eligibility_text="요건 원문",
        target_departments=[],
        target_grades=grades,
    )
    assert len(extraction.target_grades) == 20
