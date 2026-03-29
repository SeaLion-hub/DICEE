"""matching_service 순수 로직."""

import pytest
from app.domain.contracts.ai_extraction import NoticeAIExtraction, ScheduleItem, ScheduleKind, TargetGrade
from app.domain.contracts.user_profile_matching_contracts import UserProfileForMatching
from app.services import matching_service
from pydantic import ValidationError


def test_matching_eligible_empty_false() -> None:
    p = UserProfileForMatching(department_codes=[], grades=[])
    assert matching_service.matching_eligible(p) is False


def test_matching_eligible_department_only() -> None:
    p = UserProfileForMatching(department_codes=["yu_cs"], grades=[])
    assert matching_service.matching_eligible(p) is True


def test_notice_matches_empty_targets() -> None:
    p = UserProfileForMatching(department_codes=["yu_cs"], grades=["3"])
    assert matching_service.notice_matches_profile(target_departments=[], target_grades=[], profile=p) is True


def test_notice_department_mismatch() -> None:
    p = UserProfileForMatching(department_codes=["yu_cs"], grades=["3"])
    assert (
        matching_service.notice_matches_profile(
            target_departments=["전기전자공학부"],
            target_grades=[],
            profile=p,
        )
        is False
    )


def test_notice_department_match_by_label() -> None:
    p = UserProfileForMatching(department_codes=["yu_cs"], grades=["3"])
    assert (
        matching_service.notice_matches_profile(
            target_departments=["컴퓨터과학과"],
            target_grades=[],
            profile=p,
        )
        is True
    )


def test_grade_all_passes() -> None:
    p = UserProfileForMatching(department_codes=["yu_cs"], grades=["3"])
    assert (
        matching_service.notice_matches_profile(
            target_departments=[],
            target_grades=["all"],
            profile=p,
        )
        is True
    )


def test_grade_intersection() -> None:
    p = UserProfileForMatching(department_codes=["yu_cs"], grades=["3"])
    assert (
        matching_service.notice_matches_profile(
            target_departments=[],
            target_grades=["3"],
            profile=p,
        )
        is True
    )
    assert (
        matching_service.notice_matches_profile(
            target_departments=[],
            target_grades=["4"],
            profile=p,
        )
        is False
    )


def test_notice_row_matches_from_ai_json() -> None:
    ex = NoticeAIExtraction(
        raw_eligibility_text="컴퓨터과학과 3학년 대상",
        target_departments=["컴퓨터과학과"],
        target_grades=[TargetGrade.THREE],
        schedules=[ScheduleItem(kind=ScheduleKind.OTHER, starts_at=None, date_raw="추후 공지")],
    )
    raw = ex.model_dump(mode="json")
    p = UserProfileForMatching(department_codes=["yu_cs"], grades=["3"])
    assert matching_service.notice_row_matches_profile(ai_extracted_json=raw, profile=p) is True


def test_not_eligible_always_false() -> None:
    p = UserProfileForMatching(department_codes=[], grades=[])
    assert (
        matching_service.notice_matches_profile(
            target_departments=[],
            target_grades=[],
            profile=p,
        )
        is False
    )


def test_user_profile_unknown_department_raises() -> None:
    with pytest.raises(ValidationError):
        UserProfileForMatching(department_codes=["no_such"], grades=[])
