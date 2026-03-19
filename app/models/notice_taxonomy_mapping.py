"""Notice taxonomy normalized mapping model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.notice import Notice


class NoticeTaxonomyMapping(Base):
    """공지 1건의 taxonomy 행 단위 매핑 (notice_id, main_category, sub_category)."""

    __tablename__ = "notice_taxonomy_mappings"
    __table_args__ = (
        UniqueConstraint(
            "notice_id",
            "main_category",
            "sub_category",
            name="uq_notice_taxonomy_mappings_triplet",
        ),
        Index(
            "ix_notice_taxonomy_main_notice",
            "main_category",
            "notice_id",
        ),
        Index(
            "ix_notice_taxonomy_main_sub_notice",
            "main_category",
            "sub_category",
            "notice_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    notice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("notices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    main_category: Mapped[str] = mapped_column(String(64), nullable=False)
    sub_category: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    notice: Mapped["Notice"] = relationship("Notice", back_populates="taxonomy_mappings")

