"""User 관련 Pydantic 스키마."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class UserProfile(BaseModel):
    """유저 프로필 (5단계 매칭용)."""

    major: str | None = None
    grade: int | None = None
    military_served: bool | None = None
    gpa: float | None = None


class UserBase(BaseModel):
    """User 공통 필드."""

    email: str | None = None
    name: str | None = None
    profile_json: dict[str, Any] | None = None


class UserCreate(UserBase):
    """User 생성 (OAuth upsert 시)."""

    provider: str
    provider_user_id: str


class UserResponse(BaseModel):
    """User 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    provider_user_id: str
    email: str | None = None
    name: str | None = None
    profile_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
