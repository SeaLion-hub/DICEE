"""NoticeContent(공지 본문 URL). 본문은 S3에 저장되고 DB에는 content_url만 저장."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.notice import Notice


class NoticeContent(Base):
    """공지 본문은 S3 등 오브젝트 스토리지에 저장. DB에는 content_url만 보관."""

    __tablename__ = "notice_contents"

    notice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("notices.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    content_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    notice: Mapped["Notice"] = relationship("Notice", back_populates="notice_content", uselist=False)
