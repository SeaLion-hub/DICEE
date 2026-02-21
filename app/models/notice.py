"""Notice(공지) 모델. AI 추출 데이터(날짜, 지원자격) 중심의 유연한 구조로 설계."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.college import College
    from app.models.user_calendar_event import UserCalendarEvent

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Notice(Base):
    __tablename__ = "notices"
    __table_args__ = (
        UniqueConstraint("college_id", "external_id", name="uq_notice_college_external"),
        Index("ix_notices_hashtags_gin", "hashtags", postgresql_using="gin"),
        Index("ix_notices_eligibility_gin", "eligibility", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # 1. 원본 데이터 보존
    raw_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    images: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    # 2. AI 분석 및 구조화 데이터 (핵심)
    # AI가 뽑은 날짜들: [{"type": "서류마감", "date": "2026-03-01"}, {"type": "면접", "date": "2026-03-10"}]
    dates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    # AI가 뽑은 지원 자격: ["3학년 이상", "전공 무관", "학점 3.0 이상"]
    eligibility: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # AI Raw 결과 및 기타 태그
    ai_extracted_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    hashtags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # 3. 운영용 필드
    # AI 처리 선점·멱등: pending → processing(선점) → done. FOR UPDATE SKIP LOCKED와 연동.
    ai_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_manual_edited: Mapped[bool] = mapped_column(default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    college: Mapped["College"] = relationship("College", back_populates="notices")
    user_calendar_events: Mapped[list["UserCalendarEvent"]] = relationship("UserCalendarEvent", back_populates="notice")
