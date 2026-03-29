"""공지–유저 매칭 순수 로직. ADR user-notice-matching §4."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.domain.contracts.ai_extraction import NoticeAIExtraction
from app.domain.contracts.user_profile_matching_contracts import UserProfileForMatching
from app.domain.department_catalog import official_labels_for_department_codes


def matching_eligible(profile: UserProfileForMatching) -> bool:
    return bool(profile.department_codes) or bool(profile.grades)


def _normalize_label(s: str) -> str:
    return " ".join((s or "").split())


def parse_notice_matching_fields(ai_extracted_json: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """
    ai_extracted_json에서 target_departments·target_grades 추출.
    검증 실패 시 빈 제한(브로드캐스트)으로 간주해 False Positive 지향.
    """
    if not ai_extracted_json:
        return [], []
    try:
        ex = NoticeAIExtraction.model_validate(ai_extracted_json)
        grades = [g.value for g in ex.target_grades]
        return list(ex.target_departments), grades
    except ValidationError:
        return [], []


def notice_matches_profile(
    *,
    target_departments: list[str],
    target_grades: list[str],
    profile: UserProfileForMatching,
) -> bool:
    """
    학과 축 AND 학년 축 통과 시 True.
    각 축에서 공지 쪽 빈 리스트면 해당 축 통과.
    """
    if not matching_eligible(profile):
        return False

    official = official_labels_for_department_codes(list(profile.department_codes))
    norm_official = {_normalize_label(x) for x in official}

    if target_departments:
        dept_ok = False
        for d in target_departments:
            nd = _normalize_label(d)
            if nd in norm_official:
                dept_ok = True
                break
        if not dept_ok:
            return False

    user_grades = set(profile.grades)
    if target_grades:
        notice_set = set(target_grades)
        if "all" in notice_set or "grad_all" in notice_set:
            pass
        else:
            if not user_grades.intersection(notice_set):
                return False

    return True


def notice_row_matches_profile(
    *,
    ai_extracted_json: dict[str, Any] | None,
    profile: UserProfileForMatching,
) -> bool:
    td, tg = parse_notice_matching_fields(ai_extracted_json)
    return notice_matches_profile(target_departments=td, target_grades=tg, profile=profile)
