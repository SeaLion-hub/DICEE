"""UserCalendarEvent 모델. 유저가 '내 달력에 추가'한 항목."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.notice import Notice
    from app.models.user import User

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserCalendarEvent(Base):
    """유저가 달력에 추가한 공지 일정. 한 공지를 내 달력에 중복 추가 방지."""

    __tablename__ = "user_calendar_events"
    __table_args__ = (
        Index(
            "uq_user_calendar_user_notice",
            "user_id",
            "notice_id",
            unique=True,
        ),
        Index(
            "ix_user_calendar_events_user_start_end",
            "user_id",
            "start_at",
            "end_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("notices.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 표시용 제목·시작·종료
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("now()"),
    )

    user: Mapped["User"] = relationship("User", back_populates="user_calendar_events")
    notice: Mapped["Notice"] = relationship("Notice", back_populates="user_calendar_events")
