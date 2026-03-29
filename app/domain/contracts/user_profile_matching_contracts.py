"""매칭용 유저 프로필. ADR user-notice-matching §2. services·schemas 공통."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.contracts.ai_extraction import TargetGrade
from app.domain.department_catalog import allowed_department_codes

_TARGET_GRADE_VALUES = frozenset(e.value for e in TargetGrade)


class UserProfileForMatching(BaseModel):
    """users.profile_json v1 매칭 스키마."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    schema_version: int = Field(default=1, ge=1, le=100)
    department_codes: list[str] = Field(default_factory=list)
    grades: list[str] = Field(default_factory=list)
    display_name: str | None = Field(default=None, max_length=200)

    @field_validator("department_codes", mode="before")
    @classmethod
    def _normalize_codes(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("department_codes must be a list of strings.")
        allowed = allowed_department_codes()
        out: list[str] = []
        seen: set[str] = set()
        for item in v:
            if item is None:
                continue
            if not isinstance(item, str):
                raise ValueError("department_codes entries must be strings.")
            code = item.strip()
            if not code or code in seen:
                continue
            if code not in allowed:
                raise ValueError(f"Unknown department code: {code}")
            seen.add(code)
            out.append(code)
        return out

    @field_validator("grades", mode="before")
    @classmethod
    def _normalize_grades(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("grades must be a list of strings.")
        out: list[str] = []
        seen: set[str] = set()
        for item in v:
            if item is None:
                continue
            if not isinstance(item, str):
                raise ValueError("grades entries must be strings.")
            g = item.strip()
            if not g or g in seen:
                continue
            if g not in _TARGET_GRADE_VALUES:
                raise ValueError(f"Unknown grade value: {g}")
            seen.add(g)
            out.append(g)
        return out


class UserProfileMatchingPatch(BaseModel):
    """PATCH /v1/users/me 본문. None이면 기존 값 유지."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_version: int | None = Field(default=None, ge=1, le=100)
    department_codes: list[str] | None = None
    grades: list[str] | None = None
    display_name: str | None = Field(default=None, max_length=200)

    @field_validator("department_codes", mode="before")
    @classmethod
    def _patch_codes(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        dummy = UserProfileForMatching(department_codes=v, grades=[])
        return dummy.department_codes

    @field_validator("grades", mode="before")
    @classmethod
    def _patch_grades(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        dummy = UserProfileForMatching(department_codes=[], grades=v)
        return dummy.grades


class UserMeResponse(BaseModel):
    """GET /v1/users/me 응답 DTO."""

    id: uuid.UUID
    email: str | None
    name: str | None
    profile: UserProfileForMatching
    matching_eligible: bool
