"""단과대별 크롤 소스 1건 (URL·엔진 키·커넥터 JSONB)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.college import College
    from app.models.ingestion_attempt import IngestionAttempt


class CollegeSource(Base):
    __tablename__ = "college_sources"
    __table_args__ = (
        Index(
            "uq_college_sources_one_primary",
            "college_id",
            unique=True,
            postgresql_where=text("is_primary = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    college_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("colleges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    list_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    crawler_engine_key: Mapped[str] = mapped_column(String(255), nullable=False)
    connector_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    college: Mapped["College"] = relationship("College", back_populates="sources")
    ingestion_attempts: Mapped[list["IngestionAttempt"]] = relationship(
        "IngestionAttempt",
        back_populates="college_source",
        cascade="all, delete-orphan",
    )
