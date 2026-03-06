"""
AI 추출 스키마 (4·5·6단계 공통).

Instructor response_model 및 DB ai_extracted_json / Notice 투영 필드용.
설계: docs/decisions/ai-extraction-schema.md
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import AfterValidator, Field, model_validator

from app.schemas.base import BaseSchema

_DEPARTMENT_PLACEHOLDER_VALUES = frozenset(
    {"없음", "알 수 없음", "해당없음", "해당 없음", "-", "없음.", "알수없음"}
)
_PLACEHOLDER_LOWER = frozenset({"none", "n/a", "na"})


def _reject_placeholder_departments(v: list[str]) -> list[str]:
    for s in v:
        t = (s or "").strip()
        if t and (t in _DEPARTMENT_PLACEHOLDER_VALUES or t.lower() in _PLACEHOLDER_LOWER):
            raise ValueError(
                "target_departments must not contain placeholder values (e.g. '없음', '알 수 없음'). "
                "Use empty list if no departments specified."
            )
    return v


def _reject_placeholder_date_raw(v: str | None) -> str | None:
    if v is None:
        return v
    t = v.strip()
    if not t:
        return None
    if t in _DEPARTMENT_PLACEHOLDER_VALUES or t.lower() in _PLACEHOLDER_LOWER:
        raise ValueError(
            "date_raw must not be a placeholder (e.g. '없음', '알 수 없음'). "
            "Use null or the actual date text from the notice."
        )
    if len(t) > 500:
        raise ValueError("date_raw must not exceed 500 characters.")
    return v


class NoticeCategory(str, Enum):
    RECRUITMENT = "recruitment"
    INFO = "info"
    EVENT = "event"
    OTHER = "other"


class ScheduleKind(str, Enum):
    APPLICATION_DEADLINE = "application_deadline"
    INTERVIEW = "interview"
    RESULT = "result"
    EVENT = "event"
    OTHER = "other"


class TargetGrade(str, Enum):
    ONE = "1"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    ALL = "all"


class ScheduleItem(BaseSchema):
    """
    AI가 뽑은 일정 1건.
    DB notice_schedules / Notice.dates 투영 소스.
    """

    kind: ScheduleKind = Field(
        ...,
        description="일정 종류 (마감, 면접, 결과 발표, 행사 등)",
    )
    starts_at: datetime | None = Field(
        default=None,
        description="일정 시작 시각 (KST, ISO8601 끝에 +09:00 권장)",
    )
    ends_at: datetime | None = Field(
        default=None,
        description="일정 종료 시각 (선택)",
    )
    is_all_day: bool = Field(
        default=False,
        description="하루 종일 일정인지 여부",
    )
    label: str | None = Field(
        default=None,
        description="사람이 읽기 좋은 라벨 (예: '서류 마감', '1차 면접', '사전 설명회')",
    )
    date_raw: Annotated[
        str | None,
        Field(default=None, description="파싱 불가/애매한 날짜의 원문 (예: '11월 중순', '추후 공지')"),
        AfterValidator(_reject_placeholder_date_raw),
    ] = None

    @model_validator(mode="after")
    def _normalize_all_day(self) -> ScheduleItem:
        if not self.is_all_day:
            return self
        updates: dict[str, datetime | None] = {}
        if self.starts_at is not None:
            updates["starts_at"] = self.starts_at.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if self.ends_at is not None:
            updates["ends_at"] = self.ends_at.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if not updates:
            return self
        return self.model_copy(update=updates)


class NoticeAIExtraction(BaseSchema):
    """
    4·5·6단계 공통 AI 출력 스키마.
    - Instructor response_model 로 사용.
    - DB notices.ai_extracted_json 에 그대로 저장.
    - 일부 필드는 Notice.dates / eligibility / hashtags / category 로 투영.

    자격 요건 블록은 Schema-driven CoT: raw_eligibility_text → eligibility_rules
    → target_departments → target_grades 순서로 두어 환각을 줄인다.
    """

    notice_category: NoticeCategory = Field(
        default=NoticeCategory.OTHER,
        description="공지 상위 카테고리 (모집/안내/행사 등)",
    )

    summary: str | None = Field(
        default=None,
        description="공지 내용 요약 (선택)",
    )

    schedules: list[ScheduleItem] = Field(
        default_factory=list,
        description="관련 일정 목록 (마감, 면접, OT 등)",
    )

    raw_eligibility_text: str | None = Field(
        default=None,
        description="본문에 지원 자격이 있다면, 판단이나 가공 없이 본문의 자격 요건 문장을 그대로 발췌. 없다면 null.",
    )

    eligibility_rules: list[str] = Field(
        default_factory=list,
        description="raw_eligibility_text를 바탕으로 분절한 자격 조건 리스트",
    )

    target_departments: Annotated[
        list[str],
        Field(default_factory=list, description="자격 요건에 명시된 타겟 학과 리스트 (없으면 빈 리스트)"),
        AfterValidator(_reject_placeholder_departments),
    ]

    target_grades: list[TargetGrade] = Field(
        default_factory=list,
        description="자격 요건에 명시된 타겟 학년 리스트 (예: ONE, THREE, ALL)",
    )

    hashtags: list[str] = Field(
        default_factory=list,
        description="검색/필터용 해시태그",
    )

    pipeline_version: str = Field(
        default="v1",
        description="AI 파이프라인/프롬프트 버전",
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="추가 디버깅/출처 정보 등 (선택)",
    )
