"""CrawlRun(크롤 실행 이력) 모델. 단과대별 크롤 성공/실패·적재 건수 기록."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CrawlRun(Base):
    """
    단과대 크롤 1회 실행 이력. GET /internal/crawl-stats용.

    스키마: 복합 PK (id, started_at) — RANGE(started_at) 파티셔닝 호환으로 유지.
    계약: 애플리케이션은 run_id(id)당 1행만 생성함. 리포지토리는 id로 조회 시
    order_by(started_at.desc()).limit(1)로 결정적 1행을 가정함. 동일 id 복수 행은
    생성하지 않으며, 있다면 버그 또는 수동 데이터. 장기적으로 id 단일 PK 마이그레이션 고려.
    """

    __tablename__ = "crawl_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    college_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # running | success | failed
    notices_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
