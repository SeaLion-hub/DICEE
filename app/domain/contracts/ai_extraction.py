"""
AI 추출 도메인 모델 (4·5·6단계 공통).

Instructor response_model 및 DB ai_extracted_json / Notice 투영 필드용.
서비스·스키마 계층이 공통으로 사용. 설계: docs/decisions/ai-extraction-schema.md
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

_DEPARTMENT_PLACEHOLDER_VALUES = frozenset({"없음", "알 수 없음", "해당없음", "해당 없음", "-", "없음.", "알수없음"})
_PLACEHOLDER_LOWER = frozenset({"none", "n/a", "na"})
_MAX_ELIGIBILITY_RULES = 20
_MAX_TARGET_DEPARTMENTS = 50
_MAX_TARGET_GRADES = 20
_MAX_HASHTAGS = 10
_MAX_MAIN_CATEGORIES = 8
_MAX_SUBCATEGORIES_PER_MAIN = 8


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


def _sub_category_max_len(v: str | None) -> str | None:
    if v is None:
        return v
    t = (v or "").strip()
    if not t:
        return None
    if len(t) > 64:
        raise ValueError("sub_category must not exceed 64 characters.")
    return t


class NoticeCategory(str, Enum):
    """공지 대분류 대표 라벨. AI 결과 JSON 내부에서 사용."""

    SCHOLARSHIP = "scholarship"
    EMPLOYMENT = "employment"
    EVENT = "event"
    ACADEMIC = "academic"
    ADMISSION = "admission"
    INTERNATIONAL = "international"
    OTHER = "other"


class NoticeMainCategory(str, Enum):
    """공지 분류 대분류 (Multi-label). online_viewer 리포트 기준."""

    ACADEMIC_GRADUATION = "학사/졸업"
    SCHOLARSHIP_SUPPORT = "장학/지원"
    CAREER_EMPLOYMENT = "진로/취업"
    INTERNATIONAL_EXCHANGE = "국제/교류"
    RESEARCH_LAB = "연구/실험"
    CONTEST_COMPETITION = "대회/공모전"
    CULTURE_EVENT = "문화/행사"
    CAMPUS_LIFE = "캠퍼스생활"


_MAIN_CATEGORY_ORDER: tuple[NoticeMainCategory, ...] = (
    NoticeMainCategory.ACADEMIC_GRADUATION,
    NoticeMainCategory.SCHOLARSHIP_SUPPORT,
    NoticeMainCategory.CAREER_EMPLOYMENT,
    NoticeMainCategory.INTERNATIONAL_EXCHANGE,
    NoticeMainCategory.RESEARCH_LAB,
    NoticeMainCategory.CONTEST_COMPETITION,
    NoticeMainCategory.CULTURE_EVENT,
    NoticeMainCategory.CAMPUS_LIFE,
)

_SUBCATEGORY_POOL: dict[NoticeMainCategory, frozenset[str]] = {
    NoticeMainCategory.ACADEMIC_GRADUATION: frozenset(
        {"수강/학점", "휴학/복학", "전공/이중전공", "졸업/수료", "학사일정"}
    ),
    NoticeMainCategory.SCHOLARSHIP_SUPPORT: frozenset(
        {"교내/성적장학", "가계지원/국가장학", "근로/활동장학", "외부장학"}
    ),
    NoticeMainCategory.CAREER_EMPLOYMENT: frozenset({"채용/인턴", "진로/프로그램", "고시/자격증", "창업지원"}),
    NoticeMainCategory.INTERNATIONAL_EXCHANGE: frozenset(
        {"교환/방문학생", "단기연수/캠프", "유학생지원", "어학프로그램"}
    ),
    NoticeMainCategory.RESEARCH_LAB: frozenset({"학부연구생(인턴)", "대학원진학", "연구과제/참여", "실험실안전"}),
    NoticeMainCategory.CONTEST_COMPETITION: frozenset({"교내경진대회", "외부공모전", "해커톤/아이디어"}),
    NoticeMainCategory.CULTURE_EVENT: frozenset({"특강/세미나", "축제/공연", "동아리/학생회", "봉사활동"}),
    NoticeMainCategory.CAMPUS_LIFE: frozenset({"시설/공간대여", "IT/시스템안내", "보건/복지", "기타안내"}),
}


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
    GRAD_MASTER = "grad_master"
    GRAD_PHD = "grad_phd"
    GRAD_ALL = "grad_all"
    OTHER = "other"


_AI_EXTRACTION_CONFIG = ConfigDict(
    from_attributes=True,
    validate_assignment=True,
    str_strip_whitespace=True,
    extra="forbid",
)


class ScheduleItem(BaseModel):
    """
    AI가 뽑은 일정 1건.
    DB notice_schedules / Notice.dates 투영 소스.
    """

    model_config = _AI_EXTRACTION_CONFIG

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
    start_date_raw: Annotated[
        str | None,
        Field(default=None, description="시작일만 모호할 때 원문 보존 (비대칭 처리)"),
        AfterValidator(_reject_placeholder_date_raw),
    ] = None
    end_date_raw: Annotated[
        str | None,
        Field(default=None, description="종료일만 모호할 때 원문 보존 (비대칭 처리)"),
        AfterValidator(_reject_placeholder_date_raw),
    ] = None

    @model_validator(mode="after")
    def _normalize_all_day(self) -> ScheduleItem:
        if not self.is_all_day:
            return self
        updates: dict[str, datetime | None] = {}
        if self.starts_at is not None:
            updates["starts_at"] = self.starts_at.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.ends_at is not None:
            updates["ends_at"] = self.ends_at.replace(hour=0, minute=0, second=0, microsecond=0)
        if not updates:
            return self
        return self.model_copy(update=updates)

    @model_validator(mode="after")
    def _validate_date_shape(self) -> ScheduleItem:
        if (
            self.starts_at is None
            and self.ends_at is None
            and self.date_raw is None
            and self.start_date_raw is None
            and self.end_date_raw is None
        ):
            raise ValueError(
                "ScheduleItem must have at least one of starts_at, ends_at, " "date_raw, start_date_raw, end_date_raw."
            )
        if self.date_raw is not None and (self.start_date_raw is not None or self.end_date_raw is not None):
            raise ValueError(
                "Use date_raw only when both start and end are fuzzy; "
                "do not combine it with start_date_raw or end_date_raw."
            )
        if self.starts_at is not None and self.ends_at is not None and self.starts_at > self.ends_at:
            raise ValueError("starts_at must be less than or equal to ends_at.")
        return self


class TaxonomyMappingItem(BaseModel):
    """
    선택된 대분류 1개와 그 하위 소분류 집합.
    소분류는 반드시 해당 대분류 허용 풀 내에서만 선택되어야 한다.
    """

    model_config = _AI_EXTRACTION_CONFIG

    main_category: NoticeMainCategory = Field(
        ...,
        description="선택된 대분류 (Step 1 결과)",
    )
    sub_categories: list[str] = Field(
        default_factory=list,
        description="해당 대분류 하위 소분류 목록 (Step 2 결과)",
    )

    @field_validator("sub_categories", mode="before")
    @classmethod
    def _normalize_sub_categories(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("sub_categories must be a list of strings.")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in v:
            if item is None:
                continue
            if not isinstance(item, str):
                raise ValueError("sub_categories entries must be strings.")
            t = item.strip()
            if not t:
                continue
            if t in seen:
                continue
            seen.add(t)
            cleaned.append(t)
        return cleaned[:_MAX_SUBCATEGORIES_PER_MAIN]

    @model_validator(mode="after")
    def _validate_sub_categories_in_pool(self) -> TaxonomyMappingItem:
        if not self.sub_categories:
            raise ValueError("Each taxonomy mapping must include at least one sub-category.")
        allowed = _SUBCATEGORY_POOL[self.main_category]
        invalid = [sub for sub in self.sub_categories if sub not in allowed]
        if invalid:
            raise ValueError(
                f"Invalid sub-categories for '{self.main_category.value}': {invalid}. "
                "Sub-categories must be selected only from the parent category pool."
            )
        return self


class NoticeAIExtraction(BaseModel):
    """
    4·5·6단계 공통 AI 출력 스키마.
    - Instructor response_model 로 사용.
    - DB notices.ai_extracted_json 에 그대로 저장.
    - 일부 필드는 Notice.dates / eligibility / hashtags / category / sub_category 로 투영.

    자격 요건 블록은 Schema-driven CoT: raw_eligibility_text → eligibility_rules
    → target_departments → target_grades 순서로 두어 환각을 줄인다.
    """

    model_config = _AI_EXTRACTION_CONFIG

    main_categories: list[NoticeMainCategory] = Field(
        default_factory=list,
        description=(
            "Step 1 결과 대분류 목록 (multi-label). " "'캠퍼스생활'은 fallback이므로 다른 대분류와 공존 불가."
        ),
    )
    taxonomy_mappings: list[TaxonomyMappingItem] = Field(
        default_factory=list,
        description=("Step 2 결과. main_category별 소분류 매핑 목록. " "교차 매핑(다른 대분류의 소분류 선택) 금지."),
    )

    category: NoticeCategory = Field(
        default=NoticeCategory.OTHER,
        description="공지 대분류 (장학, 취업, 행사, 학사, 입시, 국제, 기타). 본문 기준으로 하나만 선택.",
    )
    sub_category: Annotated[
        str | None,
        Field(default=None, description="대분류 하위 라벨, 최대 64자 (예: 국가장학금, 인턴 모집)"),
        AfterValidator(_sub_category_max_len),
    ] = None

    summary: str | None = Field(
        default=None,
        max_length=500,
        description="공지 내용 요약 (선택, 짧게 유지)",
    )

    schedules: list[ScheduleItem] = Field(
        default_factory=list,
        description="관련 일정 목록 (마감, 면접, OT 등)",
    )

    raw_eligibility_text: str | None = Field(
        default=None,
        max_length=2500,
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
        description="자격 요건에 명시된 타겟 학년 리스트 (예: ONE, THREE, ALL). 최대 _MAX_TARGET_GRADES개.",
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

    @field_validator("eligibility_rules", mode="before")
    @classmethod
    def _normalize_eligibility_rules(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("eligibility_rules must be a list of strings.")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in v:
            if item is None:
                continue
            if not isinstance(item, str):
                raise ValueError("eligibility_rules entries must be strings.")
            t = item.strip()
            if not t:
                continue
            if t in seen:
                continue
            seen.add(t)
            cleaned.append(t)
        return cleaned[:_MAX_ELIGIBILITY_RULES]

    @field_validator("target_departments", mode="before")
    @classmethod
    def _normalize_target_departments(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("target_departments must be a list of strings.")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in v:
            if item is None:
                continue
            if not isinstance(item, str):
                raise ValueError("target_departments entries must be strings.")
            t = item.strip()
            if not t:
                continue
            if t in seen:
                continue
            seen.add(t)
            cleaned.append(t)
        return cleaned[:_MAX_TARGET_DEPARTMENTS]

    @field_validator("hashtags", mode="before")
    @classmethod
    def _normalize_hashtags(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("hashtags must be a list of strings.")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in v:
            if item is None:
                continue
            if not isinstance(item, str):
                raise ValueError("hashtags entries must be strings.")
            t = item.strip()
            if not t:
                continue
            key = t.lower()
            if t in _DEPARTMENT_PLACEHOLDER_VALUES or key in _PLACEHOLDER_LOWER:
                continue
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(t)
        return cleaned[:_MAX_HASHTAGS]

    @field_validator("target_grades", mode="after")
    @classmethod
    def _cap_target_grades(cls, v: list[TargetGrade]) -> list[TargetGrade]:
        return v[:_MAX_TARGET_GRADES] if v else []

    @field_validator("main_categories", mode="before")
    @classmethod
    def _normalize_main_categories(cls, v: Any) -> list[NoticeMainCategory]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("main_categories must be a list.")
        cleaned: list[NoticeMainCategory] = []
        seen: set[NoticeMainCategory] = set()
        for item in v:
            enum_item = item
            if not isinstance(item, NoticeMainCategory):
                enum_item = NoticeMainCategory(item)
            if enum_item in seen:
                continue
            seen.add(enum_item)
            cleaned.append(enum_item)
        return cleaned[:_MAX_MAIN_CATEGORIES]

    @model_validator(mode="after")
    def _validate_taxonomy_block(self) -> NoticeAIExtraction:
        mapping_mains: list[NoticeMainCategory] = [item.main_category for item in self.taxonomy_mappings]
        if len(mapping_mains) != len(set(mapping_mains)):
            raise ValueError("taxonomy_mappings must not contain duplicate main_category entries.")

        main_categories = self.main_categories
        if not main_categories and mapping_mains:
            # 모델이 매핑만 채운 경우를 허용하되, 대분류 목록은 자동 정규화한다.
            ordered = [cat for cat in _MAIN_CATEGORY_ORDER if cat in set(mapping_mains)]
            self.main_categories = ordered
            main_categories = ordered

        if main_categories and not self.taxonomy_mappings:
            raise ValueError("taxonomy_mappings are required when main_categories are provided.")

        if main_categories:
            if set(main_categories) != set(mapping_mains):
                raise ValueError(
                    "main_categories and taxonomy_mappings must reference the same " "set of main categories."
                )
            if NoticeMainCategory.CAMPUS_LIFE in main_categories and len(main_categories) > 1:
                raise ValueError(
                    "'캠퍼스생활' is a fallback main category and must be assigned " "as a single category only."
                )
        return self

    @model_validator(mode="after")
    def _validate_eligibility_block(self) -> NoticeAIExtraction:
        if (self.eligibility_rules or self.target_departments or self.target_grades) and not self.raw_eligibility_text:
            raise ValueError(
                "eligibility_rules/target_departments/target_grades require " "raw_eligibility_text to be set."
            )
        return self
