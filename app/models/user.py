"""User 모델. 다중 OAuth 제공자 전제 스키마."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.user_calendar_event import UserCalendarEvent

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    """유저. OAuth 전용(provider, provider_user_id). 비밀번호 해시 없음."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id", name="uq_user_provider_uid"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider_user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 프로필 (5단계 매칭용)
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # 예: {"major": "컴퓨터공학", "grade": 3, "military_served": true, "gpa": 3.5}

    # 로그아웃/탈취 시 서버에서 Refresh 토큰 무효화. JWT refresh payload의 token_version과 일치해야 유효.
    refresh_token_version: Mapped[int] = mapped_column(default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    user_calendar_events: Mapped[list["UserCalendarEvent"]] = relationship(
        "UserCalendarEvent", back_populates="user"
    )
