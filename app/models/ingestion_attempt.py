"""DB-backed 수집 시도 (Onyx IndexAttempt 패턴 축소)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.college_source import CollegeSource
    from app.models.ingestion_batch import IngestionBatch


class IngestionAttempt(Base):
    __tablename__ = "ingestion_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    college_source_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("college_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    checkpoint_pointer: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    total_batches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_batches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_docs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_requested: Mapped[bool] = mapped_column(nullable=False, default=False)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    college_source: Mapped["CollegeSource"] = relationship("CollegeSource", back_populates="ingestion_attempts")
    batches: Mapped[list["IngestionBatch"]] = relationship(
        "IngestionBatch",
        back_populates="attempt",
        cascade="all, delete-orphan",
    )
