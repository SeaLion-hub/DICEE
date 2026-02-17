"""Notice(공지) 모델. Raw 수집과 AI 정제 결과를 같은 테이블에 단계별 컬럼으로 저장."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.college import College
    from app.models.user_calendar_event import UserCalendarEvent

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Notice(Base):
    """공지사항. raw_html → ai_extracted_json 단계별 저장."""

    __tablename__ = "notices"
    __table_args__ = (UniqueConstraint("college_id", "external_id", name="uq_notice_college_external"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # 본문 해시(3·4단계): 제목+본문 변경 감지 → 해시 달라질 때만 AI 재추출
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 관리자 수동 수정 여부 → AI 재덮어쓰기 방지, 어드민 확장용
    is_manual_edited: Mapped[bool] = mapped_column(default=False, nullable=False)

    # AI 정제 결과 (4단계)
    ai_extracted_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    hashtags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # 예: ["#신입생", "#장학"]

    # 일정 (신청 마감, 행사일 등)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    college: Mapped["College"] = relationship("College", back_populates="notices")
    user_calendar_events: Mapped[list["UserCalendarEvent"]] = relationship(
        "UserCalendarEvent", back_populates="notice"
    )
